#!/usr/bin/env bash
set -euo pipefail

input="$(cat)"
dir="$HOME/.claude/quota-meter"
mkdir -p "$dir"
printf "%s\n" "$input" > "$dir/latest-raw-statusline.json"

now="$(date +%s)"

model="$(echo "$input" | jq -r '.model.display_name // "Claude"')"
current_dir="$(echo "$input" | jq -r '.workspace.current_dir // .cwd // ""')"
project_dir="$(echo "$input" | jq -r '.workspace.project_dir // .workspace.current_dir // .cwd // ""')"
project="$(basename "$current_dir")"
project_label="$(basename "$project_dir")"

# Deterministic color per project: hash the project directory name into a
# fixed palette so any new project automatically gets a stable, distinct
# color with no per-project configuration.
palette=(33 32 160 92 208 30 125 22 94 27 129 166 62 71 202 141 214 45 199 106)
hash="$(cksum <<< "$project_label" | awk '{print $1}')"
color_idx=$(( hash % ${#palette[@]} ))
project_color="${palette[$color_idx]}"
project_badge="$(printf "\033[38;5;%sm●\033[0m \033[1m%s\033[0m" "$project_color" "$project_label")"

five_used="$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // 0 | floor')"
week_used="$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // 0 | floor')"

five_reset="$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // 0')"
week_reset="$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // 0')"

context_used="$(echo "$input" | jq -r '.context_window.used_percentage // 0 | floor')"

jq -n \
  --argjson updated_at "$now" \
  --arg model "$model" \
  --arg project "$project" \
  --argjson five_used "$five_used" \
  --argjson week_used "$week_used" \
  --argjson five_reset "$five_reset" \
  --argjson week_reset "$week_reset" \
  --argjson context_used "$context_used" \
  '{
    updated_at: $updated_at,
    model: $model,
    project: $project,
    five_hour: {
      used: $five_used,
      remaining: (100 - $five_used),
      resets_at: $five_reset
    },
    seven_day: {
      used: $week_used,
      remaining: (100 - $week_used),
      resets_at: $week_reset
    },
    context_window: {
      used: $context_used,
      remaining: (100 - $context_used)
    }
  }' > "$dir/current.json"

five_left=$(( 100 - five_used ))
week_left=$(( 100 - week_used ))
context_left=$(( 100 - context_used ))

# Color escalates as the amount left shrinks: plenty left reads as calm
# green, and it steps up through amber to a bold red as it nears 0%.
color_for_left() {
  local left="$1"
  if (( left <= 10 )); then
    printf '\033[1;38;5;196m'   # bold red: critical
  elif (( left <= 25 )); then
    printf '\033[38;5;196m'     # red: low
  elif (( left <= 50 )); then
    printf '\033[38;5;220m'     # amber: caution
  else
    printf '\033[38;5;2m'       # green: plenty left
  fi
}

fmt_left() {
  local label="$1" left="$2"
  printf "%s%s %s%%\033[0m" "$(color_for_left "$left")" "$label" "$left"
}

printf "%s | Claude %s | %s | %s | %s\n" \
  "$project_badge" "$model" \
  "$(fmt_left "5h" "$five_left")" \
  "$(fmt_left "week" "$week_left")" \
  "$(fmt_left "ctx" "$context_left")"
