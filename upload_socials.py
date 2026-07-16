# -*- coding: utf-8 -*-
"""
Uploads the latest generated video to Instagram Reels and TikTok.
"""
import glob
import os
import sys
import time
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
VIDEOS_DIR = os.path.join(BASE, "videos")

def upload_instagram(video_path, description):
    load_dotenv(os.path.join(BASE, ".env"))
    username = os.environ.get("INSTA_USERNAME")
    password = os.environ.get("INSTA_PASSWORD")
    
    if not username or not password:
        print("⚠️ Παράλειψη Instagram: Δεν βρέθηκαν INSTA_USERNAME και INSTA_PASSWORD στο .env")
        return False
        
    print(f"[{video_path}] Σύνδεση στο Instagram ως {username}...")
    try:
        from instagrapi import Client
        cl = Client()
        cl.login(username, password)
        print("Επιτυχής σύνδεση! Ανέβασμα Reel...")
        cl.clip_upload(video_path, description)
        print("✅ Επιτυχές ανέβασμα στο Instagram!")
        return True
    except Exception as e:
        print(f"❌ Σφάλμα Instagram: {e}")
        return False

def upload_tiktok(video_path, description):
    cookies_path = os.path.join(BASE, "cookies.txt")
    if not os.path.exists(cookies_path):
        print(f"⚠️ Παράλειψη TikTok: Δεν βρέθηκε αρχείο {cookies_path}")
        return False
        
    print(f"[{video_path}] Ανέβασμα στο TikTok μέσω cookies...")
    try:
        from tiktok_uploader.upload import upload_video
        upload_video(video_path, description=description, cookies=cookies_path)
        print("✅ Επιτυχές ανέβασμα στο TikTok!")
        return True
    except Exception as e:
        print(f"❌ Σφάλμα TikTok: {e}")
        return False

def main():
    args = sys.argv[1:]
    
    # Εύρεση πιο πρόσφατου βίντεο αν δεν δόθηκε ως όρισμα
    if not args:
        videos = sorted(glob.glob(os.path.join(VIDEOS_DIR, "*.mp4")), key=os.path.getmtime)
        if not videos:
            print("Δεν βρέθηκαν βίντεο στον φάκελο videos/")
            return 1
        video_path = videos[-1]
    else:
        video_path = args[0]
        
    if not os.path.exists(video_path):
        print(f"Το βίντεο {video_path} δεν υπάρχει.")
        return 1
        
    txt_path = video_path.replace(".mp4", ".txt")
    description = ""
    if os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            description = f.read()
    else:
        print(f"⚠️ Δεν βρέθηκε το αρχείο περιγραφής {txt_path}, η περιγραφή θα είναι κενή.")

    print(f"=== Έναρξη Upload: {os.path.basename(video_path)} ===")
    
    upload_instagram(video_path, description)
    time.sleep(5)  # μικρή παύση
    upload_tiktok(video_path, description)
    
    print("=== Τέλος ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
