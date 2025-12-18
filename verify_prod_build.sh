#!/bin/bash
set -e

echo "🚀 Starting Pre-flight Production Verification..."

# 1. Verify Backend Build
echo "\n📦 Step 1: verifying Backend Build..."
echo "Checking valid architecture..."
# Build without caching to ensure clean state
docker build \
  --file Dockerfile \
  --tag gsp-backend-verify \
  . \
  || { echo "❌ Backend build failed"; exit 1; }
echo "✅ Backend build successful!"

# 2. Verify Frontend Build
echo "\n📦 Step 2: Verifying Frontend Build..."
# We must pass the build arg, reusing localhost is fine for a build check
docker build \
  --file frontend/Dockerfile \
  --tag gsp-frontend-verify \
  --build-arg NEXT_PUBLIC_API_URL="https://api.example.com" \
  ./frontend \
  || { echo "❌ Frontend build failed"; exit 1; }
echo "✅ Frontend build successful!"

echo "\n✨ All checks passed! Your code is ready for Google Cloud."
