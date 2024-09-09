import asyncio
import os
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaRecorder, MediaRelay, MediaBlackhole
from flask import Flask, render_template, request, jsonify
import cv2
import json
import uuid
import logging
from av import VideoFrame
import argparse

app = Flask(__name__)
logger = logging.getLogger("pc")
pcs = set()
relay = MediaRelay()

class VideoTransformTrack(MediaStreamTrack):
	kind = "video"
	def __init__(self, track, transform):
		super.__init__()
		self.track = track
		self.transform = transform

	async def recv(self):
		frame = await self.track.recv()

		if self.transform == "<some tranformation>":
			pass
		else:
			return frame

@app.route('/')
def index():
	return render_template('index.html')

@app.route('/offer', methods=['POST'])
async def offer():
	params = request.get_json() # synchronous
	offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
	pc = RTCPeerConnection()
	pc_id = "PeerConnection(%s)" % uuid.uuid4()
	pcs.add(pc)

	def log_info(msg, *args):
		logger.info(pc_id + " " + msg, *args)

	log_info("Created for %s", request.remote)

	player = MediaPlayer('video=Integrated Camera', format='dshow', options={'video_size': '640x480'})
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
	def on_track(track):
		log_info("Track %s received", track.kind)
		
		if track.kind == "audio":
			pc.addTrack(player.audio)
			recorder.addTrack(track)
		elif track.kind == "video":
			pc.addTrack(relay.subscribe(track))
			if args.record_to:
				recorder.addTrack(relay.subscribe(track))
		
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
	parser.add_argument("--port", type=int, default=8000, help="Port for HTTP server")
	parser.add_argument("--record_to", help="Write received media to a file")
	parser.add_argument("--verbose", "-v", action="count")
	args = parser.parse_args()
	
	if args.verbose:
		logging.basicConfig(level=logging.DEBUG)
	else:
		logging.basicConfig(level=logging.INFO)
	
	app.run(host=args.host, port=args.port)
