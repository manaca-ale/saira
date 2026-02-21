# Stage 1: Build the application
FROM node:20-alpine as builder

# Set working directory
WORKDIR /app

# Allow docker-compose build args to influence the Vite build.
# Vite only reads env vars prefixed with VITE_ at build time.
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}

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

# Copy custom Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80
EXPOSE 80

# Start Nginx in the foreground
CMD ["nginx", "-g", "daemon off;"]
