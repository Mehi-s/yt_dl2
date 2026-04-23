#!/usr/bin/env python3
"""
YouTube Downloader - Processes commands from commands.txt
Uses pytube for downloading and youtube-search-python for searching
Video Quality: At least 360p, but lowest possible above that
"""

import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import re

try:
    from pytube import YouTube, Search, Channel
    from pytube.exceptions import VideoUnavailable, PytubeError
except ImportError:
    print("Installing required packages...")
    os.system("pip install pytube pytube-search youtube-search-python")
    from pytube import YouTube, Search, Channel
    from pytube.exceptions import VideoUnavailable, PytubeError

class YouTubeDownloader:
    def __init__(self):
        self.downloads_dir = Path("downloads")
        self.results_dir = Path("results")
        self.commands_file = Path("commands.txt")
        
        # Create directories
        self.downloads_dir.mkdir(exist_ok=True)
        self.results_dir.mkdir(exist_ok=True)
        
        # Maximum file size for GitHub (100MB limit, we'll use 90MB to be safe)
        self.max_file_size = 90 * 1024 * 1024  # 90MB
        
        # Quality settings - at least 360p but lowest possible
        self.min_quality = 360  # Minimum 360p
        self.quality_preference = ['360p', '480p', '720p']  # Order of preference (lowest first)
        
    def sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        # Remove invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        # Limit length
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
    
    def parse_resolution(self, resolution_str: str) -> int:
        """Parse resolution string to integer (e.g., '720p' -> 720)"""
        if not resolution_str:
            return 0
        try:
            return int(resolution_str.replace('p', ''))
        except ValueError:
            return 0
    
    def select_best_stream(self, yt: YouTube) -> Tuple[Optional[object], str]:
        """
        Select the best stream based on quality preferences:
        - At least 360p
        - Lowest possible quality above 360p
        - Under 90MB file size limit
        Returns (stream, quality_description)
        """
        print("  🎯 Selecting optimal video quality...")
        
        # Get all progressive streams (video + audio) sorted by resolution
        progressive_streams = yt.streams.filter(
            progressive=True, 
            file_extension='mp4'
        ).order_by('resolution')
        
        # Get adaptive streams as backup
        adaptive_streams = yt.streams.filter(
            adaptive=True, 
            file_extension='mp4',
            only_video=True
        ).order_by('resolution')
        
        # Process progressive streams
        available_qualities = []
        for stream in progressive_streams:
            res = self.parse_resolution(stream.resolution)
            if res >= self.min_quality:  # At least 360p
                size_mb = stream.filesize / (1024*1024) if stream.filesize else float('inf')
                available_qualities.append({
                    'stream': stream,
                    'resolution': res,
                    'size_mb': size_mb,
                    'type': 'progressive',
                    'fps': stream.fps if hasattr(stream, 'fps') else 30
                })
                print(f"    📊 Found: {stream.resolution} ({size_mb:.1f} MB) - Progressive")
        
        if not available_qualities:
            print("  ⚠️ No progressive streams meet quality requirements")
            print("  🔄 Trying adaptive streams with separate audio...")
            
            # Check adaptive streams
            for stream in adaptive_streams:
                res = self.parse_resolution(stream.resolution)
                if res >= self.min_quality:
                    size_mb = stream.filesize / (1024*1024) if stream.filesize else float('inf')
                    
                    # Estimate audio size (typically 3-5MB for audio)
                    estimated_total = size_mb + 5  # Add 5MB for audio
                    
                    available_qualities.append({
                        'stream': stream,
                        'resolution': res,
                        'size_mb': estimated_total,
                        'type': 'adaptive',
                        'fps': stream.fps if hasattr(stream, 'fps') else 30
                    })
                    print(f"    📊 Found: {stream.resolution} ({size_mb:.1f} MB + audio) - Adaptive")
        
        if not available_qualities:
            print("  ❌ No suitable streams found")
            return None, "No suitable quality available"
        
        # Sort by resolution (ascending - lowest first)
        available_qualities.sort(key=lambda x: x['resolution'])
        
        # Select strategy: Find the lowest quality that's at least 360p AND under size limit
        selected = None
        selection_reason = ""
        
        for quality in available_qualities:
            if quality['size_mb'] <= (self.max_file_size / (1024*1024)):
                # Found a stream that meets both quality and size requirements
                selected = quality
                selection_reason = f"Selected {quality['stream'].resolution} - " \
                                 f"lowest quality ≥360p under size limit ({quality['size_mb']:.1f} MB)"
                break
        
        if not selected:
            print("  ⚠️ All streams exceed size limit, selecting smallest available...")
            # Select the smallest stream that meets quality requirements
            available_qualities.sort(key=lambda x: x['size_mb'])
            selected = available_qualities[0]
            selection_reason = f"Selected {selected['stream'].resolution} - " \
                             f"smallest ≥360p stream ({selected['size_mb']:.1f} MB)"
        
        print(f"  ✅ {selection_reason}")
        
        return selected['stream'], selected['stream'].resolution
    
    def search_youtube(self, query: str, max_results: int = 10):
        """Search YouTube and save results"""
        print(f"🔍 Searching YouTube for: {query}")
        
        try:
            # Using pytube's Search functionality
            search_results = Search(query)
            
            results = []
            count = 0
            
            for video in search_results.results:
                if count >= max_results:
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
                    count += 1
                    print(f"  ✅ {count}. {video_info['title'][:80]}")
                except Exception as e:
                    print(f"  ⚠️ Error getting video info: {e}")
                    continue
            
            # Save results to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_file = self.results_dir / f"search_{self.sanitize_filename(query)}_{timestamp}.txt"
            
            with open(results_file, 'w', encoding='utf-8') as f:
                f.write(f"YouTube Search Results for: {query}\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                
                for i, video in enumerate(results, 1):
                    f.write(f"{i}. {video['title']}\n")
                    f.write(f"   URL: {video['url']}\n")
                    f.write(f"   Channel: {video['author']}\n")
                    f.write(f"   Duration: {video['duration']} seconds\n")
                    f.write(f"   Views: {video['views']}\n")
                    f.write("\n")
            
            # Also save as JSON for easier parsing
            json_file = self.results_dir / f"search_{self.sanitize_filename(query)}_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            
            print(f"📄 Results saved to: {results_file}")
            print(f"📄 JSON saved to: {json_file}")
            return results
            
        except Exception as e:
            print(f"❌ Search failed: {e}")
            # Fallback: try with alternative method
            try:
                print("🔄 Trying alternative search method...")
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
                
                # Save results
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                results_file = self.results_dir / f"search_{self.sanitize_filename(query)}_{timestamp}.txt"
                
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
                
                print(f"📄 Results saved to: {results_file}")
                return results
                
            except Exception as e2:
                print(f"❌ Alternative search also failed: {e2}")
                return []
    
    def download_video(self, url: str, quality: str = "lowest_360p") -> bool:
        """
        Download a YouTube video with quality settings:
        - At least 360p
        - Lowest possible quality above 360p
        """
        print(f"⬇️ Downloading video: {url}")
        print(f"🎯 Quality setting: At least 360p, lowest possible")
        
        try:
            # Create YouTube object
            yt = YouTube(url)
            
            print(f"  📹 Title: {yt.title}")
            print(f"  ⏱️ Duration: {yt.length} seconds")
            print(f"  👁️ Views: {yt.views:,}")
            print(f"  👤 Author: {yt.author}")
            
            # Select the best stream based on our quality preferences
            video_stream, selected_quality = self.select_best_stream(yt)
            
            if not video_stream:
                print("  ❌ No suitable stream found")
                return False
            
            # Handle adaptive streams (need to merge with audio)
            if hasattr(video_stream, 'includes_audio_track') and not video_stream.includes_audio_track:
                print("  🔄 Getting audio stream for adaptive video...")
                audio_stream = yt.streams.filter(only_audio=True).first()
                
                if audio_stream:
                    print(f"  📥 Downloading video: {selected_quality}")
                    print(f"  📦 Video size: {video_stream.filesize / (1024*1024):.1f} MB")
                    
                    # Download video
                    safe_title = self.sanitize_filename(yt.title)
                    video_path = video_stream.download(
                        output_path=str(self.downloads_dir),
                        filename=f"{safe_title}_video.mp4"
                    )
                    
                    print(f"  📥 Downloading audio...")
                    audio_path = audio_stream.download(
                        output_path=str(self.downloads_dir),
                        filename=f"{safe_title}_audio.mp4"
                    )
                    
                    # Merge video and audio (simplified - just save both files)
                    print("  ⚠️ Video and audio downloaded separately")
                    print("  ℹ️ Use ffmpeg to merge: ffmpeg -i video.mp4 -i audio.mp4 -c copy output.mp4")
                    
                    # Save info
                    self._save_video_info(yt, url, video_stream, video_path)
                    return True
                else:
                    print("  ❌ No audio stream available")
                    return False
            
            # Download progressive stream
            safe_title = self.sanitize_filename(yt.title)
            print(f"  📥 Downloading: {selected_quality}")
            print(f"  📦 Size: {video_stream.filesize / (1024*1024):.1f} MB")
            
            video_path = video_stream.download(
                output_path=str(self.downloads_dir),
                filename=f"{safe_title}.mp4"
            )
            
            # Save info
            self._save_video_info(yt, url, video_stream, video_path)
            
            print(f"✅ Download complete: {safe_title}.mp4")
            print(f"📊 Quality: {selected_quality}")
            return True
            
        except VideoUnavailable:
            print(f"❌ Video is unavailable: {url}")
            return False
        except PytubeError as e:
            print(f"❌ Pytube error: {e}")
            return False
        except Exception as e:
            print(f"❌ Download failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _save_video_info(self, yt: YouTube, url: str, stream, video_path: str):
        """Save video information to a text file"""
        safe_title = self.sanitize_filename(yt.title)
        info_file = self.downloads_dir / f"{safe_title}_info.txt"
        
        with open(info_file, 'w', encoding='utf-8') as f:
            f.write(f"Title: {yt.title}\n")
            f.write(f"URL: {url}\n")
            f.write(f"Duration: {yt.length} seconds\n")
            f.write(f"Views: {yt.views:,}\n")
            f.write(f"Author: {yt.author}\n")
            f.write(f"Quality: {stream.resolution}\n")
            f.write(f"File Size: {os.path.getsize(video_path) / (1024*1024):.1f} MB\n")
            f.write(f"Download Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Quality Policy: Minimum 360p, lowest possible\n")
    
    def get_channel_videos(self, channel_url: str) -> List[Dict]:
        """Get 10 most recent videos from a channel"""
        print(f"📺 Getting recent videos from channel: {channel_url}")
        
        try:
            # Create Channel object
            channel = Channel(channel_url)
            
            print(f"  📢 Channel: {channel.channel_name}")
            
            videos = []
            count = 0
            
            for video in channel.videos:
                if count >= 10:
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
                    count += 1
                    print(f"  ✅ {count}. {video_info['title'][:80]}")
                except Exception as e:
                    print(f"  ⚠️ Error getting video info: {e}")
                    continue
            
            # Save results
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            channel_name = self.sanitize_filename(channel.channel_name)
            results_file = self.results_dir / f"channel_{channel_name}_{timestamp}.txt"
            
            with open(results_file, 'w', encoding='utf-8') as f:
                f.write(f"Recent Videos from: {channel.channel_name}\n")
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
            json_file = self.results_dir / f"channel_{channel_name}_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(videos, f, indent=2, ensure_ascii=False)
            
            print(f"📄 Results saved to: {results_file}")
            print(f"📄 JSON saved to: {json_file}")
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
            # Skip comments
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
                if url and ('youtube.com' in url or 'youtu.be' in url):
                    self.download_video(url)
                    processed_commands.append(command)
                else:
                    print(f"❌ Invalid YouTube URL: {url}")
            
            # Handle channel command
            elif command.startswith('channel '):
                channel_url = command[8:].strip()
                if channel_url and 'youtube.com' in channel_url:
                    self.get_channel_videos(channel_url)
                    processed_commands.append(command)
                else:
                    print(f"❌ Invalid channel URL: {channel_url}")
            
            else:
                print(f"❌ Unknown command: {command}")
                print("  Valid commands:")
                print("    search <query> - Search for videos")
                print("    download <youtube_url> - Download video (min 360p)")
                print("    channel <channel_url> - Get recent channel videos")
        
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
        downloads = list(self.downloads_dir.glob("*.mp4"))
        if downloads:
            print(f"\n📁 Downloads ({len(downloads)} files):")
            for file in downloads:
                size_mb = os.path.getsize(file) / (1024*1024)
                # Check resolution from filename or info file
                info_file = self.downloads_dir / f"{file.stem}_info.txt"
                quality = "Unknown"
                if info_file.exists():
                    with open(info_file, 'r') as f:
                        for line in f:
                            if line.startswith("Quality:"):
                                quality = line.split(":")[1].strip()
                
                print(f"  • {file.name} ({size_mb:.1f} MB) - {quality}")
        
        # Check results
        results = list(self.results_dir.glob("*"))
        if results:
            print(f"\n📄 Results ({len(results)} files):")
            for file in results:
                if file.suffix in ['.txt', '.json']:
                    size_kb = os.path.getsize(file) / 1024
                    print(f"  • {file.name} ({size_kb:.1f} KB)")

def main():
    """Main function"""
    print("🎬 YouTube Downloader - GitHub Actions")
    print("📊 Quality Settings: Minimum 360p, Lowest Possible")
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