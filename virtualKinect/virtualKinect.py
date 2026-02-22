import cv2
import urllib.request
import os
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from pythonosc import udp_client

# 1. Auto-Download the AI Model File
model_path = 'pose_landmarker_lite.task'
if not os.path.exists(model_path):
    print("Downloading MediaPipe AI Model... (This only happens once)")
    url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
    urllib.request.urlretrieve(url, model_path)
    print("Download complete!")

# 2. Setup VMC Client
client = udp_client.SimpleUDPClient("127.0.0.1", 39539)

# 3. Initialize the New Tasks API
base_options = python.BaseOptions(model_asset_path=model_path)
options = vision.PoseLandmarkerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.VIDEO,
    min_pose_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

detector = vision.PoseLandmarker.create_from_options(options)
cap = cv2.VideoCapture(0)

print("Tracking active! Press ESC in the video window to quit.")

frame_idx = 0

while cap.isOpened():
    ret, frame = cap.read()
    if not ret: break
    
    # Mirror the frame
    frame = cv2.flip(frame, 1)
    
    # Convert BGR to RGB for MediaPipe processing
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
    
    # The Video mode requires a strictly increasing timestamp
    timestamp_ms = frame_idx * 33 
    frame_idx += 1
    
    # Process the frame
    results = detector.detect_for_video(mp_image, timestamp_ms)
    
    # The new API returns a list of poses. [0] is the first person detected.
    if results.pose_world_landmarks:
        lm = results.pose_world_landmarks[0] 
        
        # Calculate Hips center using left (23) and right (24)
        hip_x = (lm[23].x + lm[24].x) / 2
        hip_y = (lm[23].y + lm[24].y) / 2
        hip_z = (lm[23].z + lm[24].z) / 2
        
        trackers = {
            "Head": lm[0], "LeftHand": lm[15], "RightHand": lm[16], 
            "LeftFoot": lm[31], "RightFoot": lm[32]
        }
        
        # Send via VMC
        client.send_message("/VMC/Ext/Tra/Pos", ["Hips", hip_x, hip_y, hip_z, 0.0, 0.0, 0.0, 1.0])
        for name, joint in trackers.items():
            client.send_message("/VMC/Ext/Tra/Pos", [name, joint.x, joint.y, joint.z, 0.0, 0.0, 0.0, 1.0])
            
    cv2.imshow("Kinect Emulator (Tasks API)", frame)
    if cv2.waitKey(1) == 27: break

cap.release()
cv2.destroyAllWindows()