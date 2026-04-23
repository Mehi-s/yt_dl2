#!/usr/bin/env python3
"""
YouTube Downloader - Processes commands from commands.txt
Uses pytube with multiple fallback methods for reliability
Video Quality: At least 360p, but lowest possible above that
"""

import os
import sys
import json
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import re
import urllib.request
import urllib.error

# Install required packages if missing
def install_requirements():
    packages = [
        'pytube>=15.0.0',
        'yt-dlp>=2023.12.30',  # Better alternative with frequent updates
        'youtube-search-python>=1.6.6',
    ]
    
    for package in packages:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", package])
        except Exception as e:
            print(f"⚠️ Failed to install {package}: {e}")

# Try installing dependencies
try:
    install_requirements()
except:
    pass

# Try multiple import methods
YT_DLP_AVAILABLE = False
PYTUBE_AVAILABLE = False

# Try yt-dlp first (more reliable)
try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
    print("✅ Using yt-dlp as primary downloader")
except ImportError:
    print("⚠️ yt-dlp not available, trying pytube...")

# Try pytube as fallback
try:
    from pytube import YouTube, Search, Channel
    from pytube.exceptions import VideoUnavailable, PytubeError
    PYTUBE_AVAILABLE = True
    if not YT_DLP_AVAILABLE:
        print("✅ Using pytube as downloader")
except ImportError:
    if not YT_DLP_AVAILABLE:
        print("❌ Neither yt-dlp nor pytube available")
        sys.exit(1)

class YouTubeDownloader:
    def __init__(self):
        self.downloads_dir = Path("downloads")
        self.results_dir = Path("results")
        self.commands_file = Path("commands.txt")
        
        # Create directories
        self.downloads_dir.mkdir(exist_ok=True)
        self.results_dir.mkdir(exist_ok=True)
        
        # Maximum file size for GitHub (90MB)
        self.max_file_size = 90 * 1024 * 1024
        
        # Quality settings
        self.min_quality = 360
        
    def sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        if len(filename) > 200:
            filename = filename[:200]
        return filename
    
    def read_commands(self) -> List[str]:
        """Read commands from the commands file"""
        if not self.commands_file.exists():
            return []
        
        with open(self.commands_file, 'r', encoding='utf-8') as f:
            commands = [line.strip() for line in f.readlines() if line.strip()]
        
        return commands
    
    def clear_commands(self):
        """Clear the commands file after processing"""
        with open(self.commands_file, 'w', encoding='utf-8') as f:
            f.write("# YouTube Downloader Commands\n")
            f.write("# Commands:\n")
            f.write("#   search <query> - Search YouTube\n")
            f.write("#   download <url> - Download video (min 360p, lowest possible)\n")
            f.write("#   channel <url> - Get 10 recent videos from channel\n")
            f.write("# Add your commands below this line:\n\n")
    
    def download_with_ytdlp(self, url: str) -> bool:
        """Download using yt-dlp (most reliable method)"""
        print("📥 Using yt-dlp for download...")
        
        try:
            # First, extract video info without downloading
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                title = info.get('title', 'Unknown')
                duration = info.get('duration', 0)
                view_count = info.get('view_count', 0)
                uploader = info.get('uploader', 'Unknown')
                
                print(f"  📹 Title: {title}")
                print(f"  ⏱️ Duration: {duration} seconds")
                print(f"  👁️ Views: {view_count:,}")
                print(f"  👤 Channel: {uploader}")
                
                # Find best format meeting our criteria
                formats = info.get('formats', [])
                
                # Filter formats: progressive (video+audio), mp4, >=360p
                suitable_formats = []
                for fmt in formats:
                    height = fmt.get('height')
                    if height and height >= self.min_quality:
                        filesize = fmt.get('filesize') or fmt.get('filesize_approx', 0)
                        if filesize and filesize > 0:
                            suitable_formats.append({
                                'format_id': fmt['format_id'],
                                'height': height,
                                'filesize': filesize,
                                'ext': fmt.get('ext', 'mp4'),
                                'vcodec': fmt.get('vcodec', 'none'),
                                'acodec': fmt.get('acodec', 'none'),
                            })
                
                if not suitable_formats:
                    print("  ❌ No suitable formats found")
                    return False
                
                # Sort by height (ascending) to get lowest quality >=360p
                suitable_formats.sort(key=lambda x: x['height'])
                
                # Find the first format under size limit
                selected_format = None
                for fmt in suitable_formats:
                    size_mb = fmt['filesize'] / (1024*1024)
                    if size_mb <= (self.max_file_size / (1024*1024)):
                        selected_format = fmt
                        print(f"  ✅ Selected: {fmt['height']}p ({size_mb:.1f} MB)")
                        break
                
                if not selected_format:
                    # Select smallest format that meets quality requirements
                    selected_format = min(suitable_formats, key=lambda x: x['filesize'])
                    size_mb = selected_format['filesize'] / (1024*1024)
                    print(f"  ⚠️ All over size limit, selecting smallest: {selected_format['height']}p ({size_mb:.1f} MB)")
                
                # Download the video
                safe_title = self.sanitize_filename(title)
                output_template = str(self.downloads_dir / f"{safe_title}.%(ext)s")
                
                download_opts = {
                    'format': selected_format['format_id'],
                    'outtmpl': output_template,
                    'quiet': False,
                    'no_warnings': False,
                    'progress_hooks': [self._progress_hook],
                }
                
                print(f"  📥 Downloading in {selected_format['height']}p...")
                
                with yt_dlp.YoutubeDL(download_opts) as ydl:
                    ydl.download([url])
                
                # Find the downloaded file
                downloaded_files = list(self.downloads_dir.glob(f"{safe_title}.*"))
                if downloaded_files:
                    video_path = downloaded_files[0]
                    
                    # Save video info
                    info_file = self.downloads_dir / f"{safe_title}_info.txt"
                    with open(info_file, 'w', encoding='utf-8') as f:
                        f.write(f"Title: {title}\n")
                        f.write(f"URL: {url}\n")
                        f.write(f"Duration: {duration} seconds\n")
                        f.write(f"Views: {view_count:,}\n")
                        f.write(f"Author: {uploader}\n")
                        f.write(f"Quality: {selected_format['height']}p\n")
                        f.write(f"File Size: {os.path.getsize(video_path) / (1024*1024):.1f} MB\n")
                        f.write(f"Download Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"Downloader: yt-dlp\n")
                        f.write(f"Quality Policy: Minimum 360p, lowest possible\n")
                    
                    print(f"✅ Download complete: {video_path.name}")
                    return True
                
        except Exception as e:
            print(f"❌ yt-dlp download failed: {e}")
            return False
        
        return False
    
    def _progress_hook(self, d):
        """Progress hook for yt-dlp"""
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', 'N/A')
            speed = d.get('_speed_str', 'N/A')
            eta = d.get('_eta_str', 'N/A')
            print(f"  ⏳ {percent} at {speed} - ETA: {eta}", end='\r')
        elif d['status'] == 'finished':
            print(f"\n  🔄 Processing video...")
    
    def download_with_pytube(self, url: str) -> bool:
        """Download using pytube with error handling"""
        print("📥 Trying pytube download...")
        
        try:
            # Try to bypass age restriction and other blocks
            yt = YouTube(
                url,
                use_oauth=False,
                allow_oauth_cache=False
            )
            
            # Try to get video info
            try:
                title = yt.title
                duration = yt.length
                views = yt.views
                author = yt.author
            except Exception as e:
                print(f"  ⚠️ Could not get video info: {e}")
                # Try with stream filter directly
                try:
                    streams = yt.streams.filter(progressive=True, file_extension='mp4')
                    if not streams:
                        raise Exception("No streams available")
                    # Use first available stream
                    stream = streams.order_by('resolution').first()
                    if stream:
                        title = "Unknown"
                        safe_title = self.sanitize_filename(f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                        video_path = stream.download(
                            output_path=str(self.downloads_dir),
                            filename=f"{safe_title}.mp4"
                        )
                        print(f"✅ Downloaded: {safe_title}.mp4")
                        return True
                except:
                    raise e
            
            print(f"  📹 Title: {title}")
            print(f"  ⏱️ Duration: {duration} seconds")
            print(f"  👁️ Views: {views:,}")
            print(f"  👤 Author: {author}")
            
            # Get progressive streams with video+audio
            streams = yt.streams.filter(
                progressive=True,
                file_extension='mp4'
            ).order_by('resolution')
            
            if not streams:
                print("  ❌ No progressive streams available")
                return False
            
            # Find suitable streams (>=360p)
            suitable_streams = []
            for stream in streams:
                try:
                    height = int(stream.resolution.replace('p', ''))
                    if height >= self.min_quality:
                        filesize = stream.filesize
                        if filesize:
                            suitable_streams.append({
                                'stream': stream,
                                'height': height,
                                'filesize': filesize,
                            })
                except:
                    continue
            
            if not suitable_streams:
                print("  ❌ No streams meeting quality requirements")
                return False
            
            # Sort by height (ascending)
            suitable_streams.sort(key=lambda x: x['height'])
            
            # Select best stream
            selected = None
            for s in suitable_streams:
                size_mb = s['filesize'] / (1024*1024)
                if size_mb <= (self.max_file_size / (1024*1024)):
                    selected = s
                    print(f"  ✅ Selected: {s['height']}p ({size_mb:.1f} MB)")
                    break
            
            if not selected:
                selected = min(suitable_streams, key=lambda x: x['filesize'])
                size_mb = selected['filesize'] / (1024*1024)
                print(f"  ⚠️ All over size, selecting smallest: {selected['height']}p ({size_mb:.1f} MB)")
            
            # Download
            safe_title = self.sanitize_filename(title)
            print(f"  📥 Downloading in {selected['height']}p...")
            
            video_path = selected['stream'].download(
                output_path=str(self.downloads_dir),
                filename=f"{safe_title}.mp4"
            )
            
            # Save info
            info_file = self.downloads_dir / f"{safe_title}_info.txt"
            with open(info_file, 'w', encoding='utf-8') as f:
                f.write(f"Title: {title}\n")
                f.write(f"URL: {url}\n")
                f.write(f"Duration: {duration} seconds\n")
                f.write(f"Views: {views:,}\n")
                f.write(f"Author: {author}\n")
                f.write(f"Quality: {selected['height']}p\n")
                f.write(f"File Size: {os.path.getsize(video_path) / (1024*1024):.1f} MB\n")
                f.write(f"Download Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Downloader: pytube\n")
                f.write(f"Quality Policy: Minimum 360p, lowest possible\n")
            
            print(f"✅ Download complete: {safe_title}.mp4")
            return True
            
        except Exception as e:
            print(f"❌ pytube download failed: {e}")
            return False
    
    def download_video(self, url: str) -> bool:
        """Main download method with fallbacks"""
        print(f"⬇️ Downloading video: {url}")
        print(f"🎯 Quality setting: At least 360p, lowest possible")
        
        # Validate URL
        if not ('youtube.com' in url or 'youtu.be' in url):
            print("❌ Invalid YouTube URL")
            return False
        
        # Try yt-dlp first (more reliable)
        if YT_DLP_AVAILABLE:
            success = self.download_with_ytdlp(url)
            if success:
                return True
            print("🔄 yt-dlp failed, trying pytube...")
        
        # Fallback to pytube
        if PYTUBE_AVAILABLE:
            success = self.download_with_pytube(url)
            if success:
                return True
        
        # Last resort: try with direct URL
        print("🔄 Trying direct download method...")
        try:
            # Use yt-dlp with simplest options
            import yt_dlp
            ydl_opts = {
                'format': 'best[height>=360][filesize<90M]',
                'outtmpl': str(self.downloads_dir / '%(title)s.%(ext)s'),
                'quiet': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                print(f"✅ Downloaded successfully")
                return True
                
        except Exception as e:
            print(f"❌ All download methods failed: {e}")
            return False
    
    def search_youtube(self, query: str, max_results: int = 10):
        """Search YouTube and save results"""
        print(f"🔍 Searching YouTube for: {query}")
        
        try:
            # Try using youtube-search-python (most reliable)
            try:
                from youtubesearchpython import VideosSearch
                videos_search = VideosSearch(query, limit=max_results)
                results_data = videos_search.result()
                
                results = []
                for video in results_data.get('result', []):
                    video_info = {
                        'title': video.get('title', 'Unknown'),
                        'url': f"https://youtube.com/watch?v={video.get('id', '')}",
                        'duration': video.get('duration', 'Unknown'),
                        'views': video.get('viewCount', {}).get('text', 'Unknown'),
                        'author': video.get('channel', {}).get('name', 'Unknown')
                    }
                    results.append(video_info)
                    print(f"  ✅ {len(results)}. {video_info['title'][:80]}")
                
            except ImportError:
                # Fallback to pytube search
                if PYTUBE_AVAILABLE:
                    search_results = Search(query)
                    results = []
                    for video in search_results.results:
                        if len(results) >= max_results:
                            break
                        try:
                            video_info = {
                                'title': video.title,
                                'url': f"https://youtube.com/watch?v={video.video_id}",
                                'duration': str(video.length) if hasattr(video, 'length') else 'Unknown',
                                'views': video.views if hasattr(video, 'views') else 'Unknown',
                                'author': video.author if hasattr(video, 'author') else 'Unknown'
                            }
                            results.append(video_info)
                            print(f"  ✅ {len(results)}. {video_info['title'][:80]}")
                        except:
                            continue
                else:
                    raise Exception("No search module available")
            
            # Save results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_query = self.sanitize_filename(query[:50])
            
            # Save as text
            results_file = self.results_dir / f"search_{safe_query}_{timestamp}.txt"
            with open(results_file, 'w', encoding='utf-8') as f:
                f.write(f"YouTube Search Results for: {query}\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                
                for i, video in enumerate(results, 1):
                    f.write(f"{i}. {video['title']}\n")
                    f.write(f"   URL: {video['url']}\n")
                    f.write(f"   Channel: {video['author']}\n")
                    f.write(f"   Duration: {video['duration']}\n")
                    f.write(f"   Views: {video['views']}\n")
                    f.write("\n")
            
            # Save as JSON
            json_file = self.results_dir / f"search_{safe_query}_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            
            print(f"📄 Results saved to: {results_file}")
            return results
            
        except Exception as e:
            print(f"❌ Search failed: {e}")
            return []
    
    def get_channel_videos(self, channel_url: str) -> List[Dict]:
        """Get 10 most recent videos from a channel"""
        print(f"📺 Getting recent videos from channel: {channel_url}")
        
        try:
            # Try yt-dlp first for channel extraction
            if YT_DLP_AVAILABLE:
                ydl_opts = {
                    'quiet': True,
                    'extract_flat': True,
                    'playlistend': 10,
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(channel_url, download=False)
                    
                    channel_name = info.get('title', info.get('uploader', 'Unknown'))
                    print(f"  📢 Channel: {channel_name}")
                    
                    videos = []
                    entries = info.get('entries', [])
                    
                    for entry in entries[:10]:
                        if entry:
                            video_info = {
                                'title': entry.get('title', 'Unknown'),
                                'url': f"https://youtube.com/watch?v={entry.get('id', '')}",
                                'duration': str(entry.get('duration', 'Unknown')),
                                'views': entry.get('view_count', 'Unknown'),
                                'publish_date': entry.get('upload_date', 'Unknown')
                            }
                            videos.append(video_info)
                            print(f"  ✅ {len(videos)}. {video_info['title'][:80]}")
            else:
                # Fallback to pytube
                if PYTUBE_AVAILABLE:
                    channel = Channel(channel_url)
                    channel_name = channel.channel_name
                    print(f"  📢 Channel: {channel_name}")
                    
                    videos = []
                    for video in channel.videos:
                        if len(videos) >= 10:
                            break
                        try:
                            video_info = {
                                'title': video.title,
                                'url': f"https://youtube.com/watch?v={video.video_id}",
                                'duration': str(video.length) if hasattr(video, 'length') else 'Unknown',
                                'views': video.views if hasattr(video, 'views') else 'Unknown',
                                'publish_date': str(video.publish_date) if hasattr(video, 'publish_date') else 'Unknown'
                            }
                            videos.append(video_info)
                            print(f"  ✅ {len(videos)}. {video_info['title'][:80]}")
                        except:
                            continue
                else:
                    raise Exception("No channel extraction method available")
            
            # Save results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = self.sanitize_filename(channel_name)
            
            # Save as text
            results_file = self.results_dir / f"channel_{safe_name}_{timestamp}.txt"
            with open(results_file, 'w', encoding='utf-8') as f:
                f.write(f"Recent Videos from: {channel_name}\n")
                f.write(f"Channel URL: {channel_url}\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                
                for i, video in enumerate(videos, 1):
                    f.write(f"{i}. {video['title']}\n")
                    f.write(f"   URL: {video['url']}\n")
                    f.write(f"   Duration: {video['duration']}\n")
                    f.write(f"   Views: {video['views']}\n")
                    f.write(f"   Published: {video['publish_date']}\n")
                    f.write("\n")
            
            # Save as JSON
            json_file = self.results_dir / f"channel_{safe_name}_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(videos, f, indent=2, ensure_ascii=False)
            
            print(f"📄 Results saved to: {results_file}")
            return videos
            
        except Exception as e:
            print(f"❌ Failed to get channel videos: {e}")
            return []
    
    def process_commands(self):
        """Process all commands from the commands file"""
        commands = self.read_commands()
        
        if not commands:
            print("📝 No commands to process")
            return
        
        print(f"📋 Processing {len(commands)} commands...")
        print(f"🎯 Quality Policy: Minimum 360p, lowest possible quality")
        processed_commands = []
        
        for command in commands:
            if command.startswith('#'):
                continue
            
            command = command.strip().lower()
            
            if not command:
                continue
            
            print(f"\n{'='*60}")
            print(f"🔧 Processing: {command}")
            print(f"{'='*60}")
            
            # Handle search command
            if command.startswith('search '):
                query = command[7:].strip()
                if query:
                    self.search_youtube(query)
                    processed_commands.append(command)
                else:
                    print("❌ Empty search query")
            
            # Handle download command
            elif command.startswith('download '):
                url = command[9:].strip()
                if url:
                    self.download_video(url)
                    processed_commands.append(command)
                else:
                    print("❌ Empty URL")
            
            # Handle channel command
            elif command.startswith('channel '):
                channel_url = command[8:].strip()
                if channel_url:
                    self.get_channel_videos(channel_url)
                    processed_commands.append(command)
                else:
                    print("❌ Empty channel URL")
            
            else:
                print(f"❌ Unknown command: {command}")
                print("  Valid commands:")
                print("    search <query> - Search for videos")
                print("    download <youtube_url> - Download video")
                print("    channel <channel_url> - Get recent videos")
        
        # Clear processed commands
        if processed_commands:
            self.clear_commands()
            print(f"\n✅ Cleared {len(processed_commands)} processed commands")
        
        # Show summary
        self.print_summary()
    
    def print_summary(self):
        """Print summary of downloads and results"""
        print(f"\n{'='*60}")
        print("📊 SUMMARY")
        print(f"{'='*60}")
        
        # Check downloads
        downloads = list(self.downloads_dir.glob("*"))
        if downloads:
            video_files = [f for f in downloads if f.suffix in ['.mp4', '.mkv', '.webm']]
            if video_files:
                print(f"\n📁 Downloaded Videos ({len(video_files)}):")
                for file in video_files:
                    size_mb = os.path.getsize(file) / (1024*1024)
                    print(f"  • {file.name} ({size_mb:.1f} MB)")
        
        # Check results
        results = list(self.results_dir.glob("*"))
        if results:
            txt_files = [f for f in results if f.suffix == '.txt']
            json_files = [f for f in results if f.suffix == '.json']
            print(f"\n📄 Results ({len(txt_files)} text, {len(json_files)} JSON):")
            for file in txt_files[:5]:  # Show last 5
                print(f"  • {file.name}")
            if len(txt_files) > 5:
                print(f"  ... and {len(txt_files) - 5} more")

def main():
    print("🎬 YouTube Downloader - GitHub Actions")
    print("📊 Quality Settings: Minimum 360p, Lowest Possible")
    print("🔄 Using multiple download methods for reliability")
    print("=" * 60)
    
    downloader = YouTubeDownloader()
    
    # Check if running in GitHub Actions
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print("✅ Running in GitHub Actions environment")
    
    # Process commands
    downloader.process_commands()
    
    print("\n✨ Done!")

if __name__ == "__main__":
    main()
