#!/usr/bin/env bash
# Usage: ./scripts/release.sh v1.2.20 "Short description of release"
# Requires: GITHUB_TOKEN env var set to a Personal Access Token with repo scope

set -e

VERSION="${1:?Usage: release.sh <version> <title>}"
TITLE="${2:-$VERSION}"
OWNER="ashdin01"
REPO="BackOfficePro"

if [[ -z "$GITHUB_TOKEN" ]]; then
    echo "Enter GitHub Personal Access Token (repo scope):"
    read -rs GITHUB_TOKEN
    echo
fi

# 1. Tag and push
git tag "$VERSION"
git push origin "$VERSION"
echo "✓ Tag $VERSION pushed"

# 2. Create GitHub release via API
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST \
    -H "Authorization: Bearer $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/$OWNER/$REPO/releases" \
    -d "{
        \"tag_name\": \"$VERSION\",
        \"target_commitish\": \"main\",
        \"name\": \"$TITLE\",
        \"body\": \"\",
        \"draft\": false,
        \"prerelease\": false
    }")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [[ "$HTTP_CODE" == "201" ]]; then
    URL=$(echo "$BODY" | grep -o '"html_url": *"[^"]*"' | head -1 | cut -d'"' -f4)
    echo "✓ Release created: $URL"
else
    echo "✗ GitHub API error (HTTP $HTTP_CODE):"
    echo "$BODY" | grep -o '"message": *"[^"]*"'
    exit 1
fi
