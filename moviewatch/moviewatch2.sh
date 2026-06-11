#!/bin/bash
# Directory containing your movie files
WATCH_DIR="$HOME/Documents"

# Directory to store .mov files that have been converted
ARCHIVE_DIR="$WATCH_DIR/mov_files_that_have_been_converted_to_webm"
# Directory to store long .mov files (over five minutes)
LONG_DIR="$WATCH_DIR/mov_files_longer_than_five_minutes"
# Directory to store .mov files older than three days
OLDER_DIR="$WATCH_DIR/mov_files_older_than_three_days"

for tool in ffprobe ffmpeg bc; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "moviewatch2: ERROR: '$tool' not found in PATH: $PATH" >&2
    exit 1
  fi
done

echo "moviewatch2: watching $WATCH_DIR for *.mov every 10s"

# Create the archive folders if they don't exist
mkdir -p "$ARCHIVE_DIR"
mkdir -p "$LONG_DIR"
mkdir -p "$OLDER_DIR"

# Function to get the duration (in seconds) of a .mov file using ffprobe
get_duration() {
  local mov_file="$1"
  # Use ffprobe to extract the duration in seconds (floating point)
  ffprobe -v error -select_streams v:0 -show_entries stream=duration \
    -of default=noprint_wrappers=1:nokey=1 "$mov_file"
}

# Function to process a .mov file: check age, duration, and convert or archive accordingly.
process_file() {
  local mov_file="$1"
  local base_name
  base_name=$(basename "$mov_file" .mov)
  local webm_file="$WATCH_DIR/${base_name}.webm"

  # If a corresponding .webm already exists, archive the .mov file.
  if [ -f "$webm_file" ]; then
    echo "WebM already exists for $mov_file, archiving $mov_file."
    mv "$mov_file" "$ARCHIVE_DIR/"
    return
  fi

  # Check if the file is older than three days.
  # Note: On macOS, 'stat -f %m' returns the modification time in epoch seconds.
  local mod_time
  mod_time=$(stat -f %m "$mov_file")
  local now
  now=$(date +%s)
  local age=$(( now - mod_time ))
  if (( age > 259200 )); then
    echo "File $mov_file is older than three days ($age seconds). Moving to OLDER_DIR."
    mv "$mov_file" "$OLDER_DIR/"
    return
  fi

  # Check the duration of the file (in seconds)
  local duration
  duration=$(get_duration "$mov_file")
  # If ffprobe fails to get duration, assume 0 (and proceed with conversion)
  if [ -z "$duration" ]; then
    duration=0
  fi

  # If the duration is longer than 300 seconds (5 minutes), move it to LONG_DIR.
  if (( $(echo "$duration > 300" | bc -l) )); then
    echo "File $mov_file is longer than 5 minutes ($duration seconds). Moving to LONG_DIR."
    mv "$mov_file" "$LONG_DIR/"
    return
  fi

  # Otherwise, convert the file to .webm
  echo "Converting $mov_file to $webm_file (duration: $duration seconds)."
  ffmpeg -i "$mov_file" "$webm_file"
  if [ $? -eq 0 ]; then
    echo "Conversion succeeded for $mov_file, archiving original."
    mv "$mov_file" "$ARCHIVE_DIR/"
    afplay /System/Library/Sounds/Glass.aiff
  else
    echo "Conversion failed for $mov_file, leaving file in place."
  fi
}

# Main loop: check every 10 seconds for new .mov files
while true; do
  # Loop over each .mov file in the WATCH_DIR
  for file in "$WATCH_DIR"/*.mov; do
    # If no .mov file exists, skip (this prevents literal "*.mov" when no match)
    [ -e "$file" ] || continue
    process_file "$file"
  done
  # Sleep for 10 seconds before scanning again
  sleep 10
done
