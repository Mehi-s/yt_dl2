#!/usr/bin/env python3
"""
YouTube Downloader using pytubefix with PO Token support
Video Quality: At least 360p, but lowest possible above that
"""

import os
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import re

def install_dependencies():
    """Install required packages"""
    packages = [
        'pytubefix>=6.0.0',
        'youtube-search-python>=1.6.6',
        'nodejs-wheel-binaries',  # For automatic PO token generation
    ]
    
    for package in packages:
        try:
            print(f"Installing {package}...")
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", package
            ])
        except Exception as e:
            print(f"⚠️ Failed to install {package}: {e}")

# Install dependencies
install_dependencies()

# Import after installation
try:
    from pytubefix import YouTube
    from pytubefix.cli import on_progress
    from pytubefix.exceptions import VideoUnavailable, PytubeFixError, BotDetectionError
    print("✅ pytubefix loaded successfully")
except ImportError:
    print("❌ Failed to import pytubefix")
    sys.exit(1)

class YouTubeDownloader:
    def __init__(self):
        self.downloads_dir = Path("downloads")
        self.results_dir = Path("results")
        self.commands_file = Path("commands.txt")
        self.po_token_file = Path("po_token.txt")
        self.visitor_data_file = Path("visitor_data.txt")
        
        # Create directories
        self.downloads_dir.mkdir(exist_ok=True)
        self.results_dir.mkdir(exist_ok=True)
        
        # Maximum file size for GitHub (90MB)
        self.max_file_size = 90 * 1024 * 1024  # 90MB
        
        # Quality settings
        self.min_quality = 360  # Minimum 360p
        
        # Load PO token if available
        self.po_token = None
        self.visitor_data = None
        self.load_tokens()
        
    def load_tokens(self):
        """Load PO token and visitor data from files"""
        if self.po_token_file.exists():
            with open(self.po_token_file, 'r') as f:
                self.po_token = f.read().strip()
                if self.po_token:
                    print("✅ Loaded PO token from file")
        
        if self.visitor_data_file.exists():
            with open(self.visitor_data_file, 'r') as f:
                self.visitor_data = f.read().strip()
                if self.visitor_data:
                    print("✅ Loaded visitor data from file")
    
    def sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        filename = filename.encode('ascii', 'ignore').decode('ascii')
        if len(filename) > 150:
            filename = filename[:150]
        filename = filename.strip('. ')
        return filename or "video"
    
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
            f.write("#   download <url> - Download video\n")
            f.write("#   search <query> - Search YouTube\n")
            f.write("# Add your commands below this line:\n\n")
    
    def progress_function(self, stream, chunk, bytes_remaining):
        """Progress callback for download"""
        total_size = stream.filesize
        bytes_downloaded = total_size - bytes_remaining
        percentage = (bytes_downloaded / total_size) * 100
        print(f"\r  ⏳ Downloading: {percentage:.1f}% complete", end='')
        if bytes_remaining == 0:
            print("\n  ✅ Download complete, processing...")
    
    def create_youtube_object(self, url: str) -> Optional[YouTube]:
        """Create YouTube object with various authentication methods"""
        methods = [
            # Method 1: Try with WEB client and automatic PO token
            lambda: YouTube(url, client='WEB'),
            
            # Method 2: Try with WEB_EMBED client (less restrictive)
            lambda: YouTube(url, client='WEB_EMBED'),
            
            # Method 3: Try with use_po_token if we have tokens
            lambda: YouTube(url, use_po_token=True) if self.po_token and self.visitor_data else None,
            
            # Method 4: Try with po_token parameter directly
            lambda: YouTube(url, po_token=self.po_token, visitor_data=self.visitor_data) if self.po_token and self.visitor_data else None,
            
            # Method 5: Try with ANDROID client
            lambda: YouTube(url, client='ANDROID'),
            
            # Method 6: Try with IOS client
            lambda: YouTube(url, client='IOS'),
            
            # Method 7: Default (last resort)
            lambda: YouTube(url),
        ]
        
        for i, method in enumerate(methods, 1):
            try:
                print(f"  🔄 Trying connection method {i}...")
                yt = method()
                if yt:
                    # Test if we can access the video
                    try:
                        # Try to get title as connection test
                        title = yt.title
                        if title and "detected as a bot" not in str(title).lower():
                            print(f"  ✅ Connected successfully (method {i})")
                            return yt
                    except Exception as e:
                        if "detected as a bot" in str(e).lower():
                            print(f"  ⚠️ Method {i} detected as bot, trying next...")
                            continue
                        # Other errors might mean the video is fine but title failed
                        print(f"  ⚠️ Method {i} connected but title check failed: {e}")
                        return yt  # Return anyway, might still work
                        
            except BotDetectionError:
                print(f"  ⚠️ Method {i}: Bot detected")
                continue
            except Exception as e:
                print(f"  ⚠️ Method {i} failed: {e}")
                continue
        
        print("  ❌ All connection methods failed")
        return None
    
    def get_video_stream(self, yt: YouTube) -> Tuple[Optional[object], str]:
        """Get the best video stream meeting our quality requirements"""
        print("  🎯 Analyzing available streams...")
        
        try:
            # Get progressive streams (video + audio)
            streams = yt.streams.filter(
                progressive=True,
                file_extension='mp4'
            ).order_by('resolution')
            
            if not streams:
                print("  ⚠️ No progressive streams, trying adaptive...")
                streams = yt.streams.filter(
                    adaptive=True,
                    file_extension='mp4'
                ).order_by('resolution')
            
            if not streams:
                print("  ❌ No streams available")
                return None, "No streams"
            
            # Filter and sort streams
            suitable_streams = []
            for stream in streams:
                try:
                    res_str = stream.resolution
                    if not res_str:
                        continue
                    
                    height = int(res_str.replace('p', ''))
                    
                    if height >= self.min_quality:
                        filesize = stream.filesize_approx or stream.filesize
                        if filesize and filesize > 0:
                            size_mb = filesize / (1024 * 1024)
                            suitable_streams.append({
                                'stream': stream,
                                'height': height,
                                'filesize': filesize,
                                'size_mb': size_mb,
                                'resolution': res_str,
                            })
                            print(f"    📊 {res_str} - {size_mb:.1f} MB")
                except (ValueError, AttributeError):
                    continue
            
            if not suitable_streams:
                print(f"  ❌ No streams ≥ {self.min_quality}p")
                return None, "No suitable quality"
            
            # Sort by height (ascending - lowest first)
            suitable_streams.sort(key=lambda x: x['height'])
            
            print(f"  📋 Available: {', '.join([s['resolution'] for s in suitable_streams])}")
            
            # Select lowest quality that fits under 90MB
            selected = None
            for stream_info in suitable_streams:
                if stream_info['size_mb'] <= 90:
                    selected = stream_info
                    break
            
            if not selected:
                selected = suitable_streams[0]  # Smallest available
                print(f"  ⚠️ All exceed 90MB, selecting smallest")
            
            print(f"  ✅ Selected: {selected['resolution']} ({selected['size_mb']:.1f} MB)")
            return selected['stream'], selected['resolution']
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return None, "Error"
    
    def download_video(self, url: str) -> bool:
        """Download a YouTube video"""
        print(f"\n{'='*60}")
        print(f"⬇️ Downloading: {url}")
        print(f"{'='*60}")
        
        # Create YouTube object with multiple auth methods
        yt = self.create_youtube_object(url)
        
        if not yt:
            print("❌ Could not access video. Possible solutions:")
            print("   1. Add PO token to po_token.txt")
            print("   2. Add visitor data to visitor_data.txt")
            print("   3. Try again later")
            print("   See: https://pytubefix.readthedocs.io/en/latest/user/po_token.html")
            return False
        
        try:
            # Get video information
            try:
                title = yt.title
                duration = yt.length
                views = yt.views
                author = yt.author
            except Exception as e:
                print(f"  ⚠️ Could not get full video info: {e}")
                title = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                duration = 0
                views = 0
                author = "Unknown"
            
            print(f"  📹 Title: {title[:100]}")
            if duration:
                print(f"  ⏱️ Duration: {duration} seconds")
            if author and author != "Unknown":
                print(f"  👤 Author: {author}")
            
            # Get stream
            video_stream, quality = self.get_video_stream(yt)
            
            if not video_stream:
                return False
            
            # Prepare filename and download
            safe_title = self.sanitize_filename(title)
            filesize = video_stream.filesize_approx or video_stream.filesize
            
            print(f"\n  📥 Downloading {quality}...")
            if filesize:
                print(f"  📦 Size: {filesize / (1024*1024):.1f} MB")
            
            # Download with progress
            video_path = video_stream.download(
                output_path=str(self.downloads_dir),
                filename=f"{safe_title}.mp4",
                skip_existing=False
            )
            
            print(f"\n  ✅ Download complete!")
            print(f"  📁 Saved: {Path(video_path).name}")
            
            # Save video info
            info_file = self.downloads_dir / f"{safe_title}_info.txt"
            with open(info_file, 'w', encoding='utf-8') as f:
                f.write("=== VIDEO INFORMATION ===\n")
                f.write(f"Title: {title}\n")
                f.write(f"URL: {url}\n")
                f.write(f"Duration: {duration} seconds\n")
                f.write(f"Views: {views:,}\n")
                f.write(f"Author: {author}\n")
                f.write(f"Quality: {quality}\n")
                f.write(f"File Size: {os.path.getsize(video_path) / (1024*1024):.1f} MB\n")
                f.write(f"Download Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Quality Policy: Minimum 360p, lowest possible\n")
            
            return True
            
        except Exception as e:
            print(f"  ❌ Download failed: {e}")
            return False
    
    def search_youtube(self, query: str, max_results: int = 10):
        """Search YouTube and save results"""
        print(f"\n{'='*60}")
        print(f"🔍 Searching: {query}")
        print(f"{'='*60}")
        
        try:
            from youtubesearchpython import VideosSearch
            
            videos_search = VideosSearch(query, limit=max_results)
            results_data = videos_search.result()
            
            results = []
            for i, video in enumerate(results_data.get('result', []), 1):
                video_info = {
                    'title': video.get('title', 'Unknown'),
                    'url': f"https://youtube.com/watch?v={video.get('id', '')}",
                    'duration': video.get('duration', 'Unknown'),
                    'views': video.get('viewCount', {}).get('text', 'Unknown'),
                    'author': video.get('channel', {}).get('name', 'Unknown'),
                }
                results.append(video_info)
                print(f"  {i}. {video_info['title'][:80]}")
                print(f"     {video_info['url']}")
            
            # Save results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_query = self.sanitize_filename(query[:50])
            
            results_file = self.results_dir / f"search_{safe_query}_{timestamp}.txt"
            with open(results_file, 'w', encoding='utf-8') as f:
                f.write(f"YouTube Search Results\n")
                f.write(f"Query: {query}\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                
                for i, video in enumerate(results, 1):
                    f.write(f"{i}. {video['title']}\n")
                    f.write(f"   URL: {video['url']}\n")
                    f.write(f"   Channel: {video['author']}\n")
                    f.write(f"   Duration: {video['duration']}\n")
                    f.write(f"   Views: {video['views']}\n")
                    f.write("\n")
            
            json_file = self.results_dir / f"search_{safe_query}_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            
            print(f"\n📄 Results saved to:")
            print(f"   • {results_file}")
            print(f"   • {json_file}")
            
            return results
            
        except ImportError:
            print("❌ youtube-search-python not installed")
            return []
        except Exception as e:
            print(f"❌ Search failed: {e}")
            return []
    
    def process_commands(self):
        """Process all commands from commands.txt"""
        commands = self.read_commands()
        
        if not commands:
            print("📝 No commands to process")
            print("\n💡 Add commands to commands.txt:")
            print("   download https://www.youtube.com/watch?v=VIDEO_ID")
            print("   search your query here")
            return
        
        print(f"📋 Processing {len(commands)} commands...")
        print(f"🎯 Quality: Minimum 360p, lowest possible\n")
        
        processed = []
        failed = []
        
        for command in commands:
            if command.startswith('#'):
                continue
            
            command = command.strip()
            command_lower = command.lower()
            
            if not command:
                continue
            
            if command_lower.startswith('download '):
                url = command[9:].strip()
                
                # Extract URL if needed
                url_match = re.search(r'(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[^\s]+)', url)
                if url_match:
                    url = url_match.group(1)
                
                if url and ('youtube.com' in url or 'youtu.be' in url):
                    success = self.download_video(url)
                    if success:
                        processed.append(command)
                    else:
                        failed.append(command)
                else:
                    print(f"❌ Invalid YouTube URL")
            
            elif command_lower.startswith('search '):
                query = command[7:].strip()
                if query:
                    self.search_youtube(query)
                    processed.append(command)
            
            else:
                print(f"❌ Unknown command: {command}")
                print("   Valid commands:")
                print("   • download <youtube_url>")
                print("   • search <query>")
        
        # Clear processed commands
        if processed:
            self.clear_commands()
            print(f"\n✅ Processed: {len(processed)} commands")
            if failed:
                print(f"❌ Failed: {len(failed)} commands")
        
        self.print_summary()
    
    def print_summary(self):
        """Print summary"""
        print(f"\n{'='*60}")
        print("📊 SUMMARY")
        print(f"{'='*60}")
        
        video_files = list(self.downloads_dir.glob("*.mp4"))
        if video_files:
            print(f"\n📁 Downloads ({len(video_files)}):")
            total_size = 0
            for file in video_files:
                size_mb = os.path.getsize(file) / (1024*1024)
                total_size += size_mb
                print(f"  • {file.name} ({size_mb:.1f} MB)")
            print(f"  💾 Total: {total_size:.1f} MB")
        
        txt_files = list(self.results_dir.glob("*.txt"))
        json_files = list(self.results_dir.glob("*.json"))
        if txt_files or json_files:
            print(f"\n📄 Results: {len(txt_files)} text, {len(json_files)} JSON")

def main():
    print("=" * 60)
    print("🎬 YouTube Downloader")
    print("=" * 60)
    print("📊 Quality: Minimum 360p, lowest possible")
    print("🔧 Library: pytubefix with PO Token support")
    print("=" * 60)
    
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print("✅ Running in GitHub Actions")
    
    downloader = YouTubeDownloader()
    downloader.process_commands()
    
    print("\n✨ Done!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
