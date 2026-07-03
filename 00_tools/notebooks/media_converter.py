"""
media_converter.py
==================
A beginner-friendly module that converts audio and video files between formats.

Supported OUTPUT formats
------------------------
  Audio : mp3, wav
  Video : mp4, avi, mov, mkv  (requires a resolution, e.g. (1920, 1080))

How to use
----------
  from media_converter import convert_media

  # Local folder -> audio
  convert_media(r"C:\\Users\\me\\Downloads", output_format="mp3", input_format="mp4")

  # YouTube URL -> audio
  convert_media("https://www.youtube.com/watch?v=...", output_format="wav",
                output_folder=r"C:\\Users\\me\\Downloads")

  # Local folder -> video at 720p
  convert_media(r"C:\\Users\\me\\Downloads", output_format="mp4",
                input_format="mkv", video_resolution=(1280, 720))
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import os          # Work with file paths, folders, and directory listings
import yt_dlp      # Download media from URLs (YouTube, etc.)

# moviepy provides classes to read and write audio/video files.
from moviepy import VideoFileClip, AudioFileClip


# ---------------------------------------------------------------------------
# Constants -- lists of recognised extensions
# ---------------------------------------------------------------------------

# Any file whose extension is in this set will be treated as a video file.
# Everything else is assumed to be audio-only.
VIDEO_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "webm", "flv"}

# The output formats the user is allowed to choose from.
AUDIO_OUT_FORMATS = {"mp3", "wav"}
VIDEO_OUT_FORMATS = {"mp4", "avi", "mov", "mkv"}


# ---------------------------------------------------------------------------
# Helper: clean up a file name
# ---------------------------------------------------------------------------
def make_safe_filename(name):
    """
    Remove characters that Windows does not allow in file names.

    Input
    -----
    name : str
        The raw file name, e.g. 'My Song: Live <2024>'

    Output
    ------
    str
        The cleaned name, e.g. 'My Song Live 2024'
    """
    for character in '<>:"|?*':
        name = name.replace(character, "")
    return name


# ---------------------------------------------------------------------------
# Helper: convert a single file
# ---------------------------------------------------------------------------
def convert_single_file(
    source_path,
    destination_path,
    source_extension,
    output_type,
    video_resolution=None,
):
    """
    Read one media file, convert it, and save the result.

    Inputs
    ------
    source_path       : str   -- full path to the input file
    destination_path  : str   -- full path where the converted file is saved
    source_extension  : str   -- lowercase extension of the input (e.g. 'mp4')
    output_type       : str   -- 'audio' or 'video'
    video_resolution  : tuple or None
        (width, height) for video output, e.g. (1920, 1080).
        Ignored when output_type is 'audio'.

    Output
    ------
    bool -- True if the conversion succeeded, False otherwise.
    """
    try:
        if output_type == "audio":
            # --- AUDIO OUTPUT ---
            # AudioFileClip can read the audio track from ANY file
            # (video containers like .mp4/.webm, or pure audio like .mp3/.wav).
            clip = AudioFileClip(source_path)
            clip.write_audiofile(destination_path)
            clip.close()

        else:
            # --- VIDEO OUTPUT ---
            # We need the video track, so open with VideoFileClip.
            clip = VideoFileClip(source_path)

            if video_resolution is not None:
                # Resize the video to the chosen width x height.
                clip = clip.resized(video_resolution)

            clip.write_videofile(destination_path)
            clip.close()

        print("   [OK] Conversion complete.")
        return True

    except Exception as error:
        # If anything goes wrong, print the error and keep going.
        print(f"   [ERROR] {error}")
        return False


# ---------------------------------------------------------------------------
# Main function -- the only one you need to call
# ---------------------------------------------------------------------------
def convert_media(
    input_source,
    output_format,
    input_format=None,
    output_folder=None,
    prefix="",
    suffix="",
    video_resolution=None,
):
    """
    Convert media from a local folder or a URL.

    Inputs
    ------
    input_source : str
        EITHER a folder path   (e.g. r'C:\\Users\\me\\Downloads')
        OR     a URL           (e.g. 'https://www.youtube.com/watch?v=...')

    output_format : str
        Target format.
          Audio choices : 'mp3', 'wav'
          Video choices : 'mp4', 'avi', 'mov', 'mkv'

    input_format : str or None   (default None)
        Extension of files to look for in the local folder.
        REQUIRED for local-folder mode  (e.g. 'mp4', 'wav').
        IGNORED  for URL mode.

    output_folder : str or None  (default None)
        Where to save results.
          Local mode : defaults to the same folder as the input.
          URL mode   : defaults to your current working directory.

    prefix : str   (default "")
        Text added BEFORE the base file name.
        Example: prefix='converted_' turns 'song.wav' into 'converted_song.mp3'.

    suffix : str   (default "")
        Text added AFTER the base file name (before the extension).

    video_resolution : tuple or None   (default None)
        (width, height) in pixels.  If set to None the original resolution
        is kept (no resizing).  Common choices:
          None          -- keep original (e.g. 4K stays 4K)
          (1920, 1080)  -- Full HD
          (1280, 720)   -- HD / 720p
          (640, 480)    -- SD

    Output
    ------
    Converted files are written to output_folder.
    Progress messages and any errors are printed to the screen.
    """

    # -- 1. Validate the requested output format -------------------------
    out_ext = output_format.lower().strip(".")

    # Combine both sets so we can check in one step.
    all_valid_formats = AUDIO_OUT_FORMATS | VIDEO_OUT_FORMATS

    if out_ext not in all_valid_formats:
        print(f"Error: '{out_ext}' is not a supported output format.")
        print(f"  Audio formats : {sorted(AUDIO_OUT_FORMATS)}")
        print(f"  Video formats : {sorted(VIDEO_OUT_FORMATS)}")
        return

    # -- 2. Decide whether the user wants audio or video output ----------
    output_type = "audio" if out_ext in AUDIO_OUT_FORMATS else "video"

    # If video output was chosen and no resolution was given, the
    # original resolution will be kept (no resizing).
    if output_type == "video" and video_resolution is None:
        print("Note: No video_resolution set -- original resolution will be kept.")
        print("  To resize, add:  video_resolution=(width, height)")
        print("  Common options:  (1920,1080)  (1280,720)  (640,480)\n")

    # -- 3. Detect whether the input is a URL or a local folder ----------
    is_url = input_source.startswith("http://") or input_source.startswith(
        "https://"
    )

    # ===================================================================
    #  URL MODE -- download from the internet, then convert
    # ===================================================================
    if is_url:
        # Where to save the final file (default: current working directory).
        dest = output_folder or os.getcwd()
        os.makedirs(dest, exist_ok=True)  # create the folder if it's missing

        print(f"Downloading: {input_source} ...\n")

        # Choose the yt-dlp download quality based on what we need:
        #   Audio output -> 'bestaudio/best'
        #       Downloads only the audio stream. No merging, no ffmpeg needed.
        #   Video output -> 'bestvideo+bestaudio/best'
        #       Downloads video + audio separately, then merges them.
        #       This is how you get 4K / highest resolution.
        #       NOTE: merging requires ffmpeg installed on your system.
        #       Install ffmpeg via:  conda install ffmpeg
        if output_type == "audio":
            dl_format = "bestaudio/best"
        else:
            dl_format = "bestvideo+bestaudio/best"

        download_options = {
            "format": dl_format,
            "outtmpl": os.path.join(dest, "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }

        try:
            # Download the media file.
            with yt_dlp.YoutubeDL(download_options) as downloader:
                info = downloader.extract_info(input_source, download=True)
                downloaded_file = downloader.prepare_filename(info)
                downloaded_ext = downloaded_file.rsplit(".", 1)[-1].lower()
                title = info.get("title", "media")

            # Build the final output file name.
            out_name = make_safe_filename(f"{prefix}{title}{suffix}.{out_ext}")
            out_path = os.path.join(dest, out_name)

            print(f"Converting: {title} -> {out_name} ...")
            convert_single_file(
                downloaded_file, out_path, downloaded_ext,
                output_type, video_resolution,
            )

            # Clean up the temporary raw download to save disk space.
            try:
                os.remove(downloaded_file)
            except OSError:
                pass

        except Exception as error:
            print(f"   [ERROR] {error}")
        return

    # ===================================================================
    #  LOCAL FOLDER MODE -- scan a folder and convert matching files
    # ===================================================================
    folder = input_source

    if not os.path.exists(folder):
        print(f"Error: folder '{folder}' not found.")
        return

    if input_format is None:
        print("Error: input_format is required for local folders.")
        print('  Example: input_format="mp4"')
        return

    in_ext = input_format.lower().strip(".")
    dest = output_folder or folder
    os.makedirs(dest, exist_ok=True)

    print(f"Scanning: {folder}  for .{in_ext} files ...\n")

    converted_count = 0
    for filename in os.listdir(folder):
        # Only process files whose extension matches the requested input.
        if filename.lower().endswith(f".{in_ext}"):
            # Strip the old extension to get the base name.
            base_name = filename[: -(len(in_ext) + 1)]
            out_name = f"{prefix}{base_name}{suffix}.{out_ext}"

            print(f"Converting: {filename} -> {out_name} ...")
            success = convert_single_file(
                os.path.join(folder, filename),
                os.path.join(dest, out_name),
                in_ext, output_type, video_resolution,
            )
            if success:
                converted_count += 1

    print(f"\nDone! Converted {converted_count} file(s).")
