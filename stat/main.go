package main

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode"

	_ "modernc.org/sqlite"
)

type Post struct {
	ID               int    `json:"id"`
	Platform         string `json:"platform"`
	Author           string `json:"author"`
	Content          string `json:"content"`
	CreatedAt        string `json:"created_at"`
	Sentiment        string `json:"sentiment,omitempty"`
	SentimentScore   int    `json:"sentiment_score"`
	SentimentVersion string `json:"sentiment_version,omitempty"`
}

type StatsRequest struct {
	IncludeKeywords []string `json:"include_keywords"`
	ExcludeKeywords []string `json:"exclude_keywords"`
	FromDate        string   `json:"from_date"`
	ToDate          string   `json:"to_date"`
	ExampleLimit    int      `json:"example_limit"`
	PostLimit       int      `json:"post_limit"`
}

type KeywordCount struct {
	Keyword string `json:"keyword"`
	Count   int    `json:"count"`
}

type TrendPoint struct {
	Date  string `json:"date"`
	Count int    `json:"count"`
}

type StatsResponse struct {
	MentionCount int            `json:"mention_count"`
	TopKeywords  []KeywordCount `json:"top_keywords"`
	Trends       []TrendPoint   `json:"trends"`
	ExamplePosts []Post         `json:"example_posts"`
	Posts        []Post         `json:"posts"`
}

type InsertPostRequest struct {
	Platform  string `json:"platform"`
	Author    string `json:"author"`
	Content   string `json:"content"`
	CreatedAt string `json:"created_at"`
}

type InsertPostResponse struct {
	ID int `json:"id"`
}

var stopWords = map[string]bool{
	"the": true, "a": true, "an": true, "and": true, "or": true, "to": true,
	"of": true, "in": true, "on": true, "for": true, "with": true, "is": true,
	"are": true, "it": true, "this": true, "that": true, "my": true, "our": true,
	"your": true, "but": true, "from": true, "at": true, "was": true,
}

func parseDateRange(fromDate, toDate string) (string, string, error) {
	layout := "2006-01-02"
	now := time.Now()

	if fromDate == "" {
		fromDate = now.AddDate(0, 0, -30).Format(layout)
	}
	if toDate == "" {
		toDate = now.Format(layout)
	}

	if _, err := time.Parse(layout, fromDate); err != nil {
		return "", "", fmt.Errorf("invalid from_date: %w", err)
	}
	if _, err := time.Parse(layout, toDate); err != nil {
		return "", "", fmt.Errorf("invalid to_date: %w", err)
	}

	return fromDate, toDate, nil
}

func containsAny(text string, words []string) bool {
	if len(words) == 0 {
		return true
	}
	l := strings.ToLower(text)
	for _, w := range words {
		w = strings.TrimSpace(strings.ToLower(w))
		if w == "" {
			continue
		}
		if strings.Contains(l, w) {
			return true
		}
	}
	return false
}

func containsNone(text string, words []string) bool {
	l := strings.ToLower(text)
	for _, w := range words {
		w = strings.TrimSpace(strings.ToLower(w))
		if w == "" {
			continue
		}
		if strings.Contains(l, w) {
			return false
		}
	}
	return true
}

func extractTopKeywords(posts []Post, include, exclude []string, topN int) []KeywordCount {
	re := regexp.MustCompile(`[a-zA-Z']+|[\p{Han}]+`)
	freq := map[string]int{}
	excludedMap := map[string]bool{}

	for _, w := range exclude {
		w = strings.ToLower(strings.TrimSpace(w))
		if w != "" {
			excludedMap[w] = true
		}
	}

	for _, post := range posts {
		tokens := extractKeywordTokens(post.Content, re)
		for _, t := range tokens {
			if isTooShortKeyword(t) || stopWords[t] || excludedMap[t] {
				continue
			}
			freq[t]++
		}
	}

	items := make([]KeywordCount, 0, len(freq))
	for k, c := range freq {
		items = append(items, KeywordCount{Keyword: k, Count: c})
	}

	sort.Slice(items, func(i, j int) bool {
		if items[i].Count == items[j].Count {
			return items[i].Keyword < items[j].Keyword
		}
		return items[i].Count > items[j].Count
	})

	if len(items) > topN {
		items = items[:topN]
	}
	return items
}

func extractKeywordTokens(content string, re *regexp.Regexp) []string {
	matches := re.FindAllString(strings.ToLower(content), -1)
	tokens := make([]string, 0, len(matches)*2)

	for _, m := range matches {
		if isHanOnly(m) {
			tokens = append(tokens, hanBigrams(m)...)
			continue
		}
		tokens = append(tokens, m)
	}

	return tokens
}

func isHanOnly(text string) bool {
	if text == "" {
		return false
	}
	for _, r := range text {
		if !unicode.Is(unicode.Han, r) {
			return false
		}
	}
	return true
}

func hanBigrams(text string) []string {
	runes := []rune(text)
	if len(runes) < 2 {
		return nil
	}
	if len(runes) == 2 {
		return []string{text}
	}

	bigrams := make([]string, 0, len(runes)-1)
	for i := 0; i < len(runes)-1; i++ {
		bigrams = append(bigrams, string(runes[i:i+2]))
	}
	return bigrams
}

func isTooShortKeyword(token string) bool {
	if isHanOnly(token) {
		return len([]rune(token)) < 2
	}
	return len(token) <= 2
}

func buildTrends(posts []Post) []TrendPoint {
	counts := map[string]int{}
	for _, p := range posts {
		if len(p.CreatedAt) >= 10 {
			counts[p.CreatedAt[:10]]++
		}
	}

	keys := make([]string, 0, len(counts))
	for k := range counts {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	trends := make([]TrendPoint, 0, len(keys))
	for _, d := range keys {
		trends = append(trends, TrendPoint{Date: d, Count: counts[d]})
	}
	return trends
}

func fetchFilteredPosts(db *sql.DB, req StatsRequest) ([]Post, error) {
	fromDate, toDate, err := parseDateRange(req.FromDate, req.ToDate)
	if err != nil {
		return nil, err
	}

	rows, err := db.Query(
		`SELECT id, platform, author, content, created_at,
		        sentiment_label, sentiment_score, sentiment_version
		 FROM posts
		 WHERE date(created_at) BETWEEN date(?) AND date(?)
		 ORDER BY datetime(created_at) DESC`,
		fromDate,
		toDate,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	posts := []Post{}
	for rows.Next() {
		var p Post
		var sentLabel sql.NullString
		var sentScore sql.NullInt64
		var sentVer sql.NullString
		if err := rows.Scan(
			&p.ID,
			&p.Platform,
			&p.Author,
			&p.Content,
			&p.CreatedAt,
			&sentLabel,
			&sentScore,
			&sentVer,
		); err != nil {
			return nil, err
		}
		if sentLabel.Valid && strings.TrimSpace(sentLabel.String) != "" {
			p.Sentiment = sentLabel.String
		}
		if sentScore.Valid {
			p.SentimentScore = int(sentScore.Int64)
		}
		if sentVer.Valid {
			p.SentimentVersion = sentVer.String
		}

		if !containsAny(p.Content, req.IncludeKeywords) {
			continue
		}
		if !containsNone(p.Content, req.ExcludeKeywords) {
			continue
		}
		posts = append(posts, p)
	}

	if req.PostLimit <= 0 {
		req.PostLimit = 500
	}
	if len(posts) > req.PostLimit {
		posts = posts[:req.PostLimit]
	}

	return posts, nil
}

func setupDatabase(db *sql.DB) error {
	if _, err := db.Exec(`
		CREATE TABLE IF NOT EXISTS posts (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			platform TEXT NOT NULL,
			author TEXT NOT NULL,
			content TEXT NOT NULL,
			created_at TEXT NOT NULL
		)
	`); err != nil {
		return err
	}
	return migrateSentimentColumns(db)
}

func migrateSentimentColumns(db *sql.DB) error {
	stmts := []string{
		`ALTER TABLE posts ADD COLUMN sentiment_label TEXT`,
		`ALTER TABLE posts ADD COLUMN sentiment_score INTEGER`,
		`ALTER TABLE posts ADD COLUMN sentiment_version TEXT`,
	}
	for _, stmt := range stmts {
		if _, err := db.Exec(stmt); err != nil {
			msg := strings.ToLower(err.Error())
			if strings.Contains(msg, "duplicate column") {
				continue
			}
			return err
		}
	}
	return nil
}

type nlpSentimentRequest struct {
	Texts []string `json:"texts"`
}

type nlpClassification struct {
	Label string `json:"label"`
	Score int    `json:"score"`
}

type nlpSentimentResponse struct {
	Classifications []nlpClassification `json:"classifications"`
}

func fetchSentimentFromNLP(nlpURL, text string) (label string, score int, err error) {
	payload := nlpSentimentRequest{Texts: []string{text}}
	body, err := json.Marshal(payload)
	if err != nil {
		return "", 0, err
	}
	endpoint := strings.TrimRight(nlpURL, "/") + "/sentiment"
	req, err := http.NewRequest(http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return "", 0, err
	}
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", 0, err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", 0, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", 0, fmt.Errorf("nlp status %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
	}
	var parsed nlpSentimentResponse
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return "", 0, err
	}
	if len(parsed.Classifications) == 0 {
		return "neutral", 0, nil
	}
	c := parsed.Classifications[0]
	return c.Label, c.Score, nil
}

func writeJSON(w http.ResponseWriter, status int, payload interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func normalizeCreatedAt(value string) (string, error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return time.Now().UTC().Format(time.RFC3339), nil
	}
	t, err := time.Parse(time.RFC3339, value)
	if err != nil {
		return "", fmt.Errorf("created_at must be RFC3339 format")
	}
	return t.UTC().Format(time.RFC3339), nil
}

func main() {
	port := os.Getenv("STAT_PORT")
	if port == "" {
		port = "8002"
	}
	sqlitePath := os.Getenv("SQLITE_PATH")
	if sqlitePath == "" {
		sqlitePath = "./listenai.db"
	}
	nlpURL := strings.TrimSpace(os.Getenv("NLP_URL"))

	db, err := sql.Open("sqlite", sqlitePath)
	if err != nil {
		log.Fatalf("failed to open sqlite: %v", err)
	}
	defer db.Close()

	if err := setupDatabase(db); err != nil {
		log.Fatalf("failed to setup database: %v", err)
	}

	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "service": "stat", "port": port})
	})

	http.HandleFunc("/stats", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
			return
		}

		var req StatsRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
			return
		}

		posts, err := fetchFilteredPosts(db, req)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}

		exampleLimit := req.ExampleLimit
		if exampleLimit <= 0 {
			exampleLimit = 5
		}

		examplePosts := posts
		if len(examplePosts) > exampleLimit {
			examplePosts = examplePosts[:exampleLimit]
		}

		resp := StatsResponse{
			MentionCount: len(posts),
			TopKeywords:  extractTopKeywords(posts, req.IncludeKeywords, req.ExcludeKeywords, 10),
			Trends:       buildTrends(posts),
			ExamplePosts: examplePosts,
			Posts:        posts,
		}
		writeJSON(w, http.StatusOK, resp)
	})

	http.HandleFunc("/posts", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
			return
		}

		var req InsertPostRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
			return
		}

		req.Platform = strings.TrimSpace(req.Platform)
		req.Author = strings.TrimSpace(req.Author)
		req.Content = strings.TrimSpace(req.Content)

		if req.Platform == "" || req.Author == "" || req.Content == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "platform, author, and content are required"})
			return
		}

		createdAt, err := normalizeCreatedAt(req.CreatedAt)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}

		result, err := db.Exec(
			`INSERT INTO posts (platform, author, content, created_at) VALUES (?, ?, ?, ?)`,
			req.Platform,
			req.Author,
			req.Content,
			createdAt,
		)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to insert post"})
			return
		}

		id64, err := result.LastInsertId()
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to retrieve inserted id"})
			return
		}

		postID := int(id64)
		if nlpURL != "" {
			label, score, err := fetchSentimentFromNLP(nlpURL, req.Content)
			if err != nil {
				log.Printf("sentiment enrich failed post_id=%d: %v", postID, err)
			} else {
				version := strings.TrimSpace(os.Getenv("SENTIMENT_CACHE_VERSION"))
				if version == "" {
					version = "nlp-v1"
				}
				if _, err := db.Exec(
					`UPDATE posts SET sentiment_label = ?, sentiment_score = ?, sentiment_version = ? WHERE id = ?`,
					label,
					score,
					version,
					postID,
				); err != nil {
					log.Printf("sentiment persist failed post_id=%d: %v", postID, err)
				}
			}
		}

		writeJSON(w, http.StatusCreated, InsertPostResponse{ID: postID})
	})

	addr := ":" + port
	log.Printf("stat service listening on %s", addr)
	if err := http.ListenAndServe(addr, nil); err != nil {
		log.Fatalf("server failed: %v", err)
	}
}
