#!/usr/bin/env python3
"""
YouTube Downloader using pytubefix - Reliable YouTube downloading
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
        'pytubefix>=6.0.0',  # Maintained fork of pytube that works
        'youtube-search-python>=1.6.6',
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
    from pytubefix.exceptions import VideoUnavailable, PytubeFixError
    print("✅ pytubefix loaded successfully")
except ImportError:
    print("❌ Failed to import pytubefix")
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
        self.max_file_size = 90 * 1024 * 1024  # 90MB
        
        # Quality settings
        self.min_quality = 360  # Minimum 360p
        
    def sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        # Remove invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        # Remove emojis and special characters
        filename = filename.encode('ascii', 'ignore').decode('ascii')
        # Limit length
        if len(filename) > 150:
            filename = filename[:150]
        # Remove leading/trailing spaces and dots
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
            f.write("# Add your commands below this line:\n\n")
    
    def progress_function(self, stream, chunk, bytes_remaining):
        """Progress callback for download"""
        total_size = stream.filesize
        bytes_downloaded = total_size - bytes_remaining
        percentage = (bytes_downloaded / total_size) * 100
        print(f"\r  ⏳ Downloading: {percentage:.1f}% complete", end='')
        if bytes_remaining == 0:
            print("\n  ✅ Download complete, processing...")
    
    def on_complete(self, stream, file_path):
        """Callback when download completes"""
        print(f"\n  ✅ File saved: {Path(file_path).name}")
    
    def get_video_stream(self, yt: YouTube, url: str) -> Tuple[Optional[object], str]:
        """
        Get the best video stream meeting our quality requirements:
        - At least 360p
        - Lowest possible quality above 360p
        - Under file size limit
        """
        print("  🎯 Analyzing available streams...")
        
        try:
            # Get progressive streams (video + audio) sorted by resolution
            streams = yt.streams.filter(
                progressive=True,
                file_extension='mp4'
            ).order_by('resolution')
            
            if not streams:
                print("  ⚠️ No progressive streams found")
                print("  🔄 Creating adaptive stream with audio...")
                return self.get_adaptive_stream(yt)
            
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
                                'fps': getattr(stream, 'fps', 30),
                                'type': 'progressive'
                            })
                            print(f"    📊 Found: {res_str} - {size_mb:.1f} MB")
                except (ValueError, AttributeError) as e:
                    continue
            
            if not suitable_streams:
                print("  ❌ No streams meet minimum quality requirement (360p)")
                return None, "No suitable quality"
            
            # Sort by height (ascending - lowest first)
            suitable_streams.sort(key=lambda x: x['height'])
            
            print(f"  📋 Available qualities (≥360p): {', '.join([s['resolution'] for s in suitable_streams])}")
            
            # Select strategy: lowest quality that fits under size limit
            selected = None
            
            # First try: find lowest quality under 90MB
            for stream_info in suitable_streams:
                if stream_info['size_mb'] <= 90:
                    selected = stream_info
                    print(f"  ✅ Selected: {stream_info['resolution']} - fits under 90MB limit ({stream_info['size_mb']:.1f} MB)")
                    break
            
            # Second try: if none fit, get the smallest one
            if not selected:
                selected = suitable_streams[0]  # Smallest resolution
                print(f"  ⚠️ All streams exceed 90MB. Selected smallest: {selected['resolution']} ({selected['size_mb']:.1f} MB)")
            
            return selected['stream'], selected['resolution']
            
        except Exception as e:
            print(f"  ❌ Error analyzing streams: {e}")
            return None, "Error"
    
    def get_adaptive_stream(self, yt: YouTube) -> Tuple[Optional[object], str]:
        """Try to get adaptive stream (video only) with separate audio"""
        try:
            video_streams = yt.streams.filter(
                adaptive=True,
                file_extension='mp4',
                only_video=True
            ).order_by('resolution')
            
            audio_stream = yt.streams.filter(
                adaptive=True,
                only_audio=True,
                file_extension='mp4'
            ).first()
            
            if not video_streams or not audio_stream:
                print("  ❌ Cannot create adaptive stream")
                return None, "No streams"
            
            # Filter by minimum quality
            suitable_videos = []
            for stream in video_streams:
                try:
                    height = int(stream.resolution.replace('p', ''))
                    if height >= self.min_quality:
                        video_size = stream.filesize_approx or stream.filesize or 0
                        audio_size = audio_stream.filesize_approx or audio_stream.filesize or 0
                        total_size = video_size + audio_size
                        
                        if total_size > 0:
                            suitable_videos.append({
                                'stream': stream,
                                'height': height,
                                'total_size': total_size,
                                'size_mb': total_size / (1024 * 1024),
                                'resolution': stream.resolution,
                            })
                            print(f"    📊 Found: {stream.resolution} (video+audio) - {total_size / (1024*1024):.1f} MB")
                except:
                    continue
            
            if not suitable_videos:
                return None, "No suitable adaptive streams"
            
            # Sort and select
            suitable_videos.sort(key=lambda x: x['height'])
            
            selected = None
            for v in suitable_videos:
                if v['size_mb'] <= 90:
                    selected = v
                    break
            
            if not selected:
                selected = suitable_videos[0]
            
            print(f"  ✅ Selected: {selected['resolution']} (adaptive) - {selected['size_mb']:.1f} MB")
            print(f"  ℹ️ Note: Video and audio will be separate files")
            
            # Store audio stream for later use
            self.audio_stream = audio_stream
            
            return selected['stream'], selected['resolution']
            
        except Exception as e:
            print(f"  ❌ Error with adaptive streams: {e}")
            return None, "Error"
    
    def download_video(self, url: str, max_retries: int = 3) -> bool:
        """
        Download a YouTube video
        Returns True if successful, False otherwise
        """
        print(f"\n{'='*60}")
        print(f"⬇️ Downloading: {url}")
        print(f"{'='*60}")
        
        retry_count = 0
        while retry_count < max_retries:
            try:
                if retry_count > 0:
                    print(f"\n  🔄 Retry attempt {retry_count + 1}/{max_retries}")
                    import time
                    time.sleep(2)  # Wait before retry
                
                # Create YouTube object with multiple client options
                print("  🔌 Connecting to YouTube...")
                
                try:
                    # Try with default client
                    yt = YouTube(
                        url,
                        on_progress_callback=self.progress_function,
                        on_complete_callback=self.on_complete,
                        use_oauth=False,
                        allow_oauth_cache=False
                    )
                except Exception:
                    # Try with different client
                    print("  🔄 Trying alternative connection method...")
                    try:
                        yt = YouTube(url)
                    except Exception as e2:
                        raise e2
                
                # Get video information
                try:
                    # Check if video is available
                    yt.check_availability()
                except Exception as e:
                    print(f"  ⚠️ Video availability check failed: {e}")
                    # Continue anyway, might still work
                
                # Get basic info
                try:
                    title = yt.title
                    duration = yt.length
                    views = yt.views
                    author = yt.author
                except Exception as e:
                    print(f"  ⚠️ Could not get video info: {e}")
                    title = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    duration = 0
                    views = 0
                    author = "Unknown"
                
                print(f"  📹 Title: {title[:100]}")
                if duration:
                    print(f"  ⏱️ Duration: {duration} seconds")
                if views:
                    print(f"  👁️ Views: {views:,}")
                if author:
                    print(f"  👤 Author: {author}")
                
                # Get the best stream
                video_stream, quality = self.get_video_stream(yt, url)
                
                if not video_stream:
                    print("  ❌ No suitable stream found")
                    retry_count += 1
                    continue
                
                # Prepare filename
                safe_title = self.sanitize_filename(title) if title else f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                
                # Download the video
                print(f"\n  📥 Starting download...")
                print(f"  🎯 Quality: {quality}")
                filesize = video_stream.filesize_approx or video_stream.filesize
                if filesize:
                    print(f"  📦 File size: {filesize / (1024*1024):.1f} MB")
                
                try:
                    video_path = video_stream.download(
                        output_path=str(self.downloads_dir),
                        filename=f"{safe_title}.mp4",
                        skip_existing=False
                    )
                    print(f"\n  ✅ Video downloaded successfully!")
                    print(f"  📁 Saved as: {Path(video_path).name}")
                    
                except Exception as download_error:
                    print(f"\n  ❌ Download failed: {download_error}")
                    
                    # Try alternative download method
                    print("  🔄 Trying alternative download method...")
                    try:
                        video_path = video_stream.download(
                            output_path=str(self.downloads_dir),
                            filename=f"{safe_title}.mp4"
                        )
                        print(f"  ✅ Downloaded with alternative method")
                    except Exception as e2:
                        raise e2
                
                # Save video info
                try:
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
                    print(f"  📄 Info saved: {info_file.name}")
                except Exception as e:
                    print(f"  ⚠️ Could not save info file: {e}")
                
                # Verify download
                if Path(video_path).exists():
                    actual_size = os.path.getsize(video_path)
                    if actual_size > 0:
                        print(f"  ✅ Download verified: {actual_size / (1024*1024):.1f} MB")
                        return True
                    else:
                        print("  ❌ Downloaded file is empty")
                        retry_count += 1
                        continue
                else:
                    print("  ❌ File not found after download")
                    retry_count += 1
                    continue
                
            except VideoUnavailable:
                print(f"  ❌ Video is unavailable (private/deleted/restricted)")
                return False
                
            except PytubeFixError as e:
                print(f"  ❌ PytubeFix error: {e}")
                retry_count += 1
                
            except Exception as e:
                print(f"  ❌ Unexpected error: {e}")
                print(f"  📝 Error type: {type(e).__name__}")
                retry_count += 1
                
                if retry_count < max_retries:
                    print(f"  🔄 Will retry in 3 seconds...")
                    import time
                    time.sleep(3)
        
        print(f"  ❌ Failed after {max_retries} attempts")
        return False
    
    def search_youtube(self, query: str, max_results: int = 10):
        """Search YouTube and save results"""
        print(f"\n{'='*60}")
        print(f"🔍 Searching YouTube: {query}")
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
                    'description': video.get('descriptionSnippet', [{}])[0].get('text', '')[:200] if video.get('descriptionSnippet') else ''
                }
                results.append(video_info)
                print(f"  ✅ {i}. {video_info['title'][:80]}")
                print(f"     {video_info['url']}")
            
            # Save results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_query = self.sanitize_filename(query[:50])
            
            # Save as text
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
                    if video['description']:
                        f.write(f"   Description: {video['description']}...\n")
                    f.write("\n")
            
            # Save as JSON
            json_file = self.results_dir / f"search_{safe_query}_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            
            print(f"\n📄 Results saved:")
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
        """Process all commands from the commands file"""
        commands = self.read_commands()
        
        if not commands:
            print("📝 No commands to process")
            print("💡 Add commands to commands.txt like:")
            print("   download https://www.youtube.com/watch?v=VIDEO_ID")
            return
        
        print(f"📋 Processing {len(commands)} commands...")
        print(f"🎯 Quality: Minimum 360p, lowest possible\n")
        
        processed = []
        failed = []
        
        for command in commands:
            if command.startswith('#'):
                continue
            
            command = command.strip()
            original_command = command
            command_lower = command.lower()
            
            if not command:
                continue
            
            # Handle download command
            if command_lower.startswith('download '):
                url = command[9:].strip()
                
                # Extract URL if command contains extra text
                url_match = re.search(r'(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[^\s]+)', url)
                if url_match:
                    url = url_match.group(1)
                
                if url and ('youtube.com' in url or 'youtu.be' in url):
                    success = self.download_video(url)
                    if success:
                        processed.append(original_command)
                        print(f"\n✅ Successfully processed: download")
                    else:
                        failed.append(original_command)
                        print(f"\n❌ Failed to process: download")
                else:
                    print(f"❌ Invalid YouTube URL")
                    print(f"   URL must contain youtube.com or youtu.be")
            
            # Handle search command
            elif command_lower.startswith('search '):
                query = command[7:].strip()
                if query:
                    self.search_youtube(query)
                    processed.append(original_command)
                else:
                    print("❌ Empty search query")
            
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
        
        # Show summary
        self.print_summary()
    
    def print_summary(self):
        """Print summary of downloads and results"""
        print(f"\n{'='*60}")
        print("📊 SUMMARY")
        print(f"{'='*60}")
        
        # Check downloads
        video_files = list(self.downloads_dir.glob("*.mp4"))
        if video_files:
            print(f"\n📁 Downloaded Videos ({len(video_files)}):")
            total_size = 0
            for file in sorted(video_files, key=lambda x: os.path.getmtime(x), reverse=True)[:5]:
                size_mb = os.path.getsize(file) / (1024*1024)
                total_size += size_mb
                print(f"  • {file.name} ({size_mb:.1f} MB)")
            if len(video_files) > 5:
                print(f"  ... and {len(video_files) - 5} more videos")
            print(f"  💾 Total size: {total_size:.1f} MB")
        
        # Check results
        txt_files = list(self.results_dir.glob("*.txt"))
        json_files = list(self.results_dir.glob("*.json"))
        if txt_files or json_files:
            print(f"\n📄 Search Results:")
            print(f"  • {len(txt_files)} text files")
            print(f"  • {len(json_files)} JSON files")

def main():
    """Main function"""
    print("=" * 60)
    print("🎬 YouTube Downloader")
    print("=" * 60)
    print("📊 Quality: Minimum 360p, lowest possible")
    print("🔧 Library: pytubefix (maintained fork)")
    print("=" * 60)
    
    # Check if running in GitHub Actions
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print("✅ Running in GitHub Actions")
    
    # Create downloader instance
    downloader = YouTubeDownloader()
    
    # Process commands
    downloader.process_commands()
    
    print("\n✨ Done!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
