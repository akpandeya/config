#!/bin/bash

# Read JSON payload from stdin
DATA=$(cat)

# Extract model display name
MODEL=$(echo "$DATA" | jq -r '.model.display_name // "Gemini"')

# Fetch quota dynamically using our node script
QUOTA_JSON=$(node /Users/dipukumari/.gemini/antigravity-cli/scratch/fetch_quota.js "$MODEL" 2>/dev/null)

COLOR_RESET=$'\e[0m'
COLOR_MODEL=$'\e[36m'      # Cyan
COLOR_RESET_TIME=$'\e[35m' # Magenta
COLOR_GREEN=$'\e[32m'
COLOR_YELLOW=$'\e[33m'
COLOR_RED=$'\e[31m'

# Function to get color based on remaining quota
get_color() {
  local rem="$1"
  if [ "$rem" -gt 50 ]; then
    echo "$COLOR_GREEN"
  elif [ "$rem" -gt 20 ]; then
    echo "$COLOR_YELLOW"
  else
    echo "$COLOR_RED"
  fi
}

# Parse results
ERR=$(echo "$QUOTA_JSON" | jq -r '.error // ""')
REMAINING=$(echo "$QUOTA_JSON" | jq -r '.remaining // ""')
RESETS_IN=$(echo "$QUOTA_JSON" | jq -r '.resets_in // ""')

# Build the output string
OUTPUT="${COLOR_MODEL}${MODEL}${COLOR_RESET}"

if [ -n "$REMAINING" ] && [ "$ERR" = "" ]; then
  COLOR_QUOTA=$(get_color "$REMAINING")
  if [ -n "$RESETS_IN" ]; then
    OUTPUT="${OUTPUT} | Quota: ${COLOR_QUOTA}${REMAINING}%${COLOR_RESET} (${COLOR_RESET_TIME}${RESETS_IN}${COLOR_RESET})"
  else
    OUTPUT="${OUTPUT} | Quota: ${COLOR_QUOTA}${REMAINING}%${COLOR_RESET}"
  fi
else
  # If error or not found, display model name only
  OUTPUT="${OUTPUT} | Quota: N/A"
fi

echo "$OUTPUT"
