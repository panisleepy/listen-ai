const express = require("express");
const cors = require("cors");
const jwt = require("jsonwebtoken");
const axios = require("axios");
const dotenv = require("dotenv");

dotenv.config();

const app = express();
const port = process.env.GATEWAY_PORT || 8000;
const statUrl = process.env.STAT_URL || "http://localhost:8002";
const nlpUrl = process.env.NLP_URL || "http://localhost:8001";
const jwtSecret = process.env.JWT_SECRET || "supersecret";
const demoUser = process.env.DEMO_USER || "admin";
const demoPass = process.env.DEMO_PASS || "admin123";

app.use(cors());
app.use(express.json());

function authMiddleware(req, res, next) {
  const authHeader = req.headers.authorization || "";
  const [, token] = authHeader.split(" ");

  if (!token) {
    return res.status(401).json({ error: "Missing bearer token" });
  }

  try {
    const payload = jwt.verify(token, jwtSecret);
    req.user = payload;
    return next();
  } catch (err) {
    return res.status(401).json({ error: "Invalid or expired token" });
  }
}

app.get("/health", (req, res) => {
  res.json({ status: "ok", service: "gateway", port });
});

app.post("/auth/login", (req, res) => {
  const { username, password } = req.body || {};

  if (username !== demoUser || password !== demoPass) {
    return res.status(401).json({ error: "Invalid credentials" });
  }

  const token = jwt.sign({ username }, jwtSecret, { expiresIn: "12h" });
  return res.json({ token });
});

app.post("/api/dashboard", authMiddleware, async (req, res) => {
  const {
    includeKeywords = [],
    excludeKeywords = [],
    fromDate = "",
    toDate = "",
    sampleSize = 5,
  } = req.body || {};

  try {
    const statResp = await axios.post(`${statUrl}/stats`, {
      include_keywords: includeKeywords,
      exclude_keywords: excludeKeywords,
      from_date: fromDate,
      to_date: toDate,
      example_limit: sampleSize,
      post_limit: 500,
    });

    const stats = statResp.data;
    const posts = Array.isArray(stats.posts) ? stats.posts : [];

    const missingIndexes = [];
    const textsNeeding = [];
    posts.forEach((p, idx) => {
      const cached = typeof p.sentiment === "string" && p.sentiment.trim() !== "";
      if (!cached) {
        missingIndexes.push(idx);
        textsNeeding.push(p.content);
      }
    });

    let classificationsByIndex = {};
    if (textsNeeding.length > 0) {
      const sentimentResp = await axios.post(`${nlpUrl}/sentiment`, { texts: textsNeeding });
      const classifications = sentimentResp.data?.classifications || [];
      missingIndexes.forEach((originalIdx, i) => {
        classificationsByIndex[originalIdx] = classifications[i];
      });
    }

    const classifiedPosts = posts.map((post, idx) => {
      const cached =
        typeof post.sentiment === "string" && post.sentiment.trim() !== "";
      if (cached) {
        return {
          ...post,
          sentiment: post.sentiment,
          sentiment_score: typeof post.sentiment_score === "number" ? post.sentiment_score : 0,
        };
      }
      const cls = classificationsByIndex[idx];
      return {
        ...post,
        sentiment: cls?.label || "neutral",
        sentiment_score: cls?.score || 0,
      };
    });

    const totals = { positive: 0, neutral: 0, negative: 0 };
    for (const row of classifiedPosts) {
      const lab = row.sentiment || "neutral";
      if (totals[lab] !== undefined) {
        totals[lab] += 1;
      } else {
        totals.neutral += 1;
      }
    }
    const denom = Math.max(1, classifiedPosts.length);
    const sentimentPercentage = {
      positive: Math.round((totals.positive / denom) * 10000) / 100,
      neutral: Math.round((totals.neutral / denom) * 10000) / 100,
      negative: Math.round((totals.negative / denom) * 10000) / 100,
    };

    const examples = classifiedPosts.slice(0, sampleSize);

    return res.json({
      sentimentPercentage,
      topKeywords: stats.top_keywords || [],
      trends: stats.trends || [],
      examplePosts: examples,
      mentionCount: stats.mention_count || 0,
      totalAnalyzedPosts: classifiedPosts.length,
      nlpCalls: textsNeeding.length,
      cachedSentiments: posts.length - textsNeeding.length,
    });
  } catch (err) {
    const detail = err.response?.data || err.message;
    return res.status(500).json({
      error: "Failed to build dashboard response",
      detail,
    });
  }
});

app.post("/api/posts", authMiddleware, async (req, res) => {
  const { platform = "", author = "", content = "", createdAt = "" } = req.body || {};

  try {
    const statResp = await axios.post(`${statUrl}/posts`, {
      platform,
      author,
      content,
      created_at: createdAt,
    });
    return res.status(201).json(statResp.data);
  } catch (err) {
    const status = err.response?.status || 500;
    const detail = err.response?.data || err.message;
    return res.status(status).json({
      error: "Failed to insert post",
      detail,
    });
  }
});

app.listen(port, () => {
  console.log(`gateway listening on :${port}`);
});
