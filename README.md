# Zoom to YouTube Uploader

A prototype tool that downloads Zoom cloud recordings and uploads them to YouTube.

## Repository Structure

This repository contains two separate prototype modules:

### Zoom Download (`prototype/zoom_download/`)

Downloads Zoom cloud recordings using OAuth authentication.

- See [`prototype/zoom_download/README.md`](prototype/zoom_download/README.md) for setup and usage instructions
- Downloads videos from Zoom cloud recordings
- Supports Gallery View and Speaker View recordings
- Configurable download settings and folder naming

### YouTube Upload (`prototype/youtube_upload/`)

Uploads videos to YouTube as unlisted videos.

- See [`prototype/youtube_upload/README.md`](prototype/youtube_upload/README.md) for setup and usage instructions
- Uploads videos from local folders to YouTube
- Supports custom titles, descriptions, and tags
- Maintains upload logs

## Quick Start

1. **Set up Zoom Download:**
   ```bash
   cd prototype/zoom_download
   # Follow instructions in prototype/zoom_download/README.md
   ```

2. **Set up YouTube Upload:**
   ```bash
   cd prototype/youtube_upload
   # Follow instructions in prototype/youtube_upload/README.md
   ```

## Notes

- Each prototype module has its own requirements file and can be set up independently
- Both modules use `.env` files for configuration:
  - Zoom: `prototype/zoom_download/.env`
  - YouTube: `prototype/youtube_upload/.env`
- The Zoom download module saves videos to `test_downloads/` in the repository root
- The YouTube upload module can upload videos from any local folder

