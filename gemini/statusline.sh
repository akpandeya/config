#!/usr/bin/env bash
# Antigravity CLI status line — mirrors the Claude Code Matrix theme style

input=$(cat)

# --- model ---
model=$(echo "$input" | jq -r '.model.display_name // ""')

# --- context window ---
remaining=$(echo "$input" | jq -r '.context_window.remaining_percentage // empty')

# Check if quota is available in the payload
has_quota=$(echo "$input" | jq -r 'if .quota then "true" else "false" end')

if [ "$has_quota" = "true" ]; then
  is_3p=$(echo "$input" | jq -r 'if (.model.id | ascii_downcase | contains("claude") or contains("gpt") or contains("3p")) then "true" else "false" end')
  if [ "$is_3p" = "true" ]; then
    prefix="3p"
  else
    prefix="gemini"
  fi
  
  five_hour_rem_frac=$(echo "$input" | jq -r ".quota[\"${prefix}-5h\"].remaining_fraction // empty")
  five_hour_res_secs=$(echo "$input" | jq -r ".quota[\"${prefix}-5h\"].reset_in_seconds // empty")
  seven_day_rem_frac=$(echo "$input" | jq -r ".quota[\"${prefix}-weekly\"].remaining_fraction // empty")
  seven_day_res_secs=$(echo "$input" | jq -r ".quota[\"${prefix}-weekly\"].reset_in_seconds // empty")
  
  # Format percentages (remainingFraction * 100)
  five_hour_rem=""
  if [ -n "$five_hour_rem_frac" ]; then
    five_hour_rem=$(printf '%.0f' "$(awk "BEGIN {print $five_hour_rem_frac * 100}")")
  fi
  seven_day_rem=""
  if [ -n "$seven_day_rem_frac" ]; then
    seven_day_rem=$(printf '%.0f' "$(awk "BEGIN {print $seven_day_rem_frac * 100}")")
  fi
  
  # Calculate countdown for 5h
  five_hour_reset_label=""
  if [ -n "$five_hour_res_secs" ] && [ -n "$five_hour_rem" ]; then
    if [ "$five_hour_res_secs" -gt 0 ]; then
      hours=$(( five_hour_res_secs / 3600 ))
      mins=$(( (five_hour_res_secs % 3600) / 60 ))
      if [ "$hours" -gt 0 ]; then
        five_hour_reset_label="resets:${hours}h${mins}m"
      else
        five_hour_reset_label="resets:${mins}m"
      fi
    else
      five_hour_reset_label="resets:soon"
    fi
  fi
  
  # Calculate countdown for 7d
  seven_day_reset_label=""
  if [ -n "$seven_day_res_secs" ] && [ -n "$seven_day_rem" ]; then
    if [ "$seven_day_res_secs" -gt 0 ]; then
      days=$(( seven_day_res_secs / 86400 ))
      hours=$(( (seven_day_res_secs % 86400) / 3600 ))
      if [ "$days" -gt 0 ]; then
        seven_day_reset_label="resets:${days}d${hours}h"
      else
        seven_day_reset_label="resets:${hours}h"
      fi
    else
      seven_day_reset_label="resets:soon"
    fi
  fi
else
  # Fallback to dynamic page evaluation using our node script
  QUOTA_JSON=$(node /Users/dipukumari/.gemini/antigravity-cli/scratch/fetch_quota.js "$model" 2>/dev/null)
  
  five_hour_rem=$(echo "$QUOTA_JSON" | jq -r '.five_hour_remaining // empty')
  five_hour_resets_at=$(echo "$QUOTA_JSON" | jq -r '.five_hour_resets_at // empty')
  seven_day_rem=$(echo "$QUOTA_JSON" | jq -r '.seven_day_remaining // empty')
  seven_day_resets_at=$(echo "$QUOTA_JSON" | jq -r '.seven_day_resets_at // empty')

  # Calculate countdown based on resets_at (Unix epoch seconds)
  five_hour_reset_label=""
  if [ -n "$five_hour_resets_at" ] && [ -n "$five_hour_rem" ]; then
    now=$(date +%s)
    diff=$(( five_hour_resets_at - now ))
    if [ "$diff" -gt 0 ]; then
      hours=$(( diff / 3600 ))
      mins=$(( (diff % 3600) / 60 ))
      if [ "$hours" -gt 0 ]; then
        five_hour_reset_label="resets:${hours}h${mins}m"
      else
        five_hour_reset_label="resets:${mins}m"
      fi
    else
      five_hour_reset_label="resets:soon"
    fi
  fi

  seven_day_reset_label=""
  if [ -n "$seven_day_resets_at" ] && [ -n "$seven_day_rem" ]; then
    now=$(date +%s)
    diff=$(( seven_day_resets_at - now ))
    if [ "$diff" -gt 0 ]; then
      days=$(( diff / 86400 ))
      hours=$(( (diff % 86400) / 3600 ))
      if [ "$days" -gt 0 ]; then
        seven_day_reset_label="resets:${days}d${hours}h"
      else
        seven_day_reset_label="resets:${hours}h"
      fi
    else
      seven_day_reset_label="resets:soon"
    fi
  fi
fi

# --- assemble ---
DIM='\033[2m'
RESET='\033[0m'

parts=()

[ -n "$model" ] && parts+=("$(printf "${DIM}%s${RESET}" "$model")")
[ -n "$remaining" ] && parts+=("$(printf "${DIM}ctx:%s%%${RESET}" "$(printf '%.0f' "$remaining")")")

if [ -n "$five_hour_rem" ]; then
  parts+=("$(printf "${DIM}5h:%s%%${RESET}" "$five_hour_rem")")
  [ -n "$five_hour_reset_label" ] && parts+=("$(printf "${DIM}%s${RESET}" "$five_hour_reset_label")")
fi

if [ -n "$seven_day_rem" ]; then
  parts+=("$(printf "${DIM}7d:%s%%${RESET}" "$seven_day_rem")")
  [ -n "$seven_day_reset_label" ] && parts+=("$(printf "${DIM}%s${RESET}" "$seven_day_reset_label")")
fi

if [ -z "$five_hour_rem" ] && [ -z "$seven_day_rem" ]; then
  parts+=("$(printf "${DIM}5h:N/A${RESET}")")
fi

printf '%s' "$(IFS=' '; echo "${parts[*]}")"
