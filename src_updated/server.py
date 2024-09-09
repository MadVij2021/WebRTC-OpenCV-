import asyncio
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.contrib.media import MediaRecorder, MediaBlackhole
from flask import Flask, render_template, request, jsonify
import cv2
import uuid
import logging
from av import VideoFrame
import argparse

app = Flask(__name__)
logger = logging.getLogger("pc")
pcs = set()
# relay = MediaRelay()

# add transformation filters on video track
class VideoTransformTrack(MediaStreamTrack):
	kind = "video"
	def __init__(self, track, transform):
		super().__init__()
		self.track = track
		self.transform = transform

	async def recv(self):
		frame = await self.track.recv()

		if self.transform == "<some tranformation>":
			pass
		else:
			return frame

class OpenCVMediaStreamTrack(MediaStreamTrack):
	kind = "video"
	
	def __init__(self, device_index=0):
		super().__init__()
		self.cam = cv2.VideoCapture(device_index)

	async def recv(self):
		success, frame = self.cam.read()
		if not success:
			raise Exception("Failed to capture frames")
		
		# Convert the image from OpenCV format to AV format
		frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
		frame = VideoFrame.from_ndarray(frame, format="rgb24")
		frame.pts = frame.time_base = None
		return frame

@app.route('/')
def index():
	return render_template('index.html')

@app.route('/offer', methods=['POST'])
async def offer():
	params = request.get_json() # synchronous
	if not params:
		return jsonify({"error": "Invalid JSON data"}), 400
	offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
	pc = RTCPeerConnection()
	pc_id = "PeerConnection(%s)" % uuid.uuid4()
	pcs.add(pc)

	def log_info(msg, *args):
		logger.info(pc_id + " " + msg, *args)

	log_info("Created for %s", request.remote_addr)

	# player = MediaPlayer('video=Integrated Camera', format='dshow', options={'frame_rate': "60", 'video_size': '640x480'})
	if args.record_to:
		recorder = MediaRecorder(args.record_to)
	else:
		recorder = MediaBlackhole()

	@pc.on("connectionstatechange")
	async def on_connectionstatechange():
		log_info("Connection state is %s", pc.connectionState)
		if pc.connectionState == "failed":
			await pc.close()
			pcs.discard(pc)

	@pc.on("track")
	async def on_track(track):
		log_info("Track %s received", track.kind)
		
		if track.kind == "audio":
			pc.addTrack(track)
			recorder.addTrack(track)
		elif track.kind == "video":
			# pc.addTrack(VideoTransformTrack(relay.subscribe(track)), transform=params["video_transform"])
			video_track = OpenCVMediaStreamTrack(device_index=0)
			pc.addTrack(VideoTransformTrack(video_track, transform=params.get("video_transform", "")))
			if args.record_to:
				recorder.addTrack(video_track)
		
		@track.on("ended")
		async def on_ended():
			log_info("Track %s ended", track.kind)
			await recorder.stop()

	# handle offer
	await pc.setRemoteDescription(offer)
	await recorder.start()

	# send answer
	answer = await pc.createAnswer()
	await pc.setLocalDescription(answer)

	# Handle offer
	# loop = asyncio.new_event_loop()
	# asyncio.set_event_loop(loop)
	# loop.run_until_complete(pc.setRemoteDescription(offer))
	# loop.run_until_complete(recorder.start())

	# # Send answer
	# answer = loop.run_until_complete(pc.createAnswer())
	# loop.run_until_complete(pc.setLocalDescription(answer))
	
	return jsonify({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})

@app.teardown_appcontext
def on_shutdown(exc):
	loop = asyncio.new_event_loop()
	asyncio.set_event_loop(loop)
	# close peer connections
	coros = [pc.close() for pc in pcs]
	asyncio.get_event_loop().run_until_complete(asyncio.gather(*coros))
	pcs.clear()
	loop.close()

@app.route('/test')
def test():
	return "Test successful"

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="WebRTC+Flask Live Streaming Application")
	parser.add_argument("--host", default="0.0.0.0", help="Host for HTTP server")
	parser.add_argument("--port", type=int, default=8080, help="Port for HTTP server")
	parser.add_argument("--record_to", help="Write received media to a file")
	parser.add_argument("--verbose", "-v", action="count")
	args = parser.parse_args()
	
	if args.verbose:
		logging.basicConfig(level=logging.DEBUG)
	else:
		logging.basicConfig(level=logging.INFO)
	
	app.run(host=args.host, port=args.port)
