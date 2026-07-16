# Stage 1: Build the application
FROM node:20-alpine as builder

# Set working directory
WORKDIR /app

# Allow docker-compose build args to influence the Vite build.
# Vite only reads env vars prefixed with VITE_ at build time.
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}

# Tela de rotulagem (/rotulagem): ferramenta interna, LIGADA só em teste.
# Ausente/false em prod => rota e ícone escondidos.
ARG VITE_ENABLE_LABELING
ENV VITE_ENABLE_LABELING=${VITE_ENABLE_LABELING}

# Copy package.json (lockfile may not exist in repo)
COPY package.json ./

# Install dependencies - using 'npm install' to resolve lockfile mismatches
RUN npm install

# Copy the rest of the source code
COPY . .

# Build the project (output will be in /app/dist)
RUN npm run build

# Stage 2: Serve the application with Nginx
FROM nginx:alpine

# Copy the build output from Stage 1 to the Nginx html directory
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy Nginx template (envsubst replaces $S3_BUCKET_HOST at runtime)
COPY nginx.conf.template /etc/nginx/nginx.conf.template

ENV S3_BUCKET_HOST=saira-images.s3.sa-east-1.amazonaws.com

# Expose port 80
EXPOSE 80

# Substitute S3_BUCKET_HOST into nginx config, then start Nginx.
# Single-quoted arg to envsubst ensures only $S3_BUCKET_HOST is replaced,
# leaving nginx variables ($host, $uri, etc.) intact.
CMD ["/bin/sh", "-c", "envsubst '$S3_BUCKET_HOST' < /etc/nginx/nginx.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
