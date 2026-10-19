FROM node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Unprivileged listen port (ADR-043): nginx runs as uid 101 (chart podSecurity),
# master included - no root, no CAP_NET_BIND_SERVICE needed on 8080.
EXPOSE 8080
