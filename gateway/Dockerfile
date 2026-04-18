FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

ENV GATEWAY_PORT=8000
ENV STAT_URL=http://stat:8002
ENV NLP_URL=http://nlp:8001
EXPOSE 8000

CMD ["npm", "run", "start"]
