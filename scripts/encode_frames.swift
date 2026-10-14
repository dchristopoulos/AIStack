// Turn the frames `record_demo.py` wrote into an H.264 MP4, with the Mac's own encoder.
//
//     swift scripts/encode_frames.swift <frames.txt> <demo.mp4>
//
// frames.txt has one line per screenshot: its path, a tab, and how many frames it is held for.
// macOS only. Anywhere else, ffmpeg's concat demuxer reads the same list with little change.

import AVFoundation
import CoreGraphics
import ImageIO

let fps: Int32 = 30
let arguments = CommandLine.arguments
guard arguments.count == 3 else { fatalError("usage: encode_frames.swift <frames.txt> <out.mp4>") }
let lines = try String(contentsOfFile: arguments[1], encoding: .utf8).split(separator: "\n")

func image(_ path: String) -> CGImage {
    let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil)!
    return CGImageSourceCreateImageAtIndex(source, 0, nil)!
}

let first = image(String(lines[0].split(separator: "\t")[0]))
let (width, height) = (first.width, first.height)
let output = URL(fileURLWithPath: arguments[2])
try? FileManager.default.removeItem(at: output)

let writer = try AVAssetWriter(outputURL: output, fileType: .mp4)
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width,
    AVVideoHeightKey: height,
    // Generous for a screen of text: sharp letters matter more here than a small file.
    AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 8_000_000,
                                      AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel],
])
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
    kCVPixelBufferWidthKey as String: width,
    kCVPixelBufferHeightKey as String: height,
])
writer.add(input)
guard writer.startWriting() else { fatalError("\(writer.error!)") }
writer.startSession(atSourceTime: .zero)

func buffer(_ picture: CGImage) -> CVPixelBuffer {
    var made: CVPixelBuffer?
    CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &made)
    let pixels = made!
    CVPixelBufferLockBaseAddress(pixels, [])
    let context = CGContext(data: CVPixelBufferGetBaseAddress(pixels), width: width, height: height,
                            bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(pixels),
                            space: CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue)!
    context.draw(picture, in: CGRect(x: 0, y: 0, width: width, height: height))
    CVPixelBufferUnlockBaseAddress(pixels, [])
    return pixels
}

var frame: Int64 = 0
for line in lines {
    let parts = line.split(separator: "\t")
    let pixels = buffer(image(String(parts[0])))
    for _ in 0..<Int(parts[1])! {
        while !input.isReadyForMoreMediaData { usleep(2000) }
        adaptor.append(pixels, withPresentationTime: CMTime(value: frame, timescale: fps))
        frame += 1
    }
}
input.markAsFinished()
let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
print("\(frame) frames, \(frame / Int64(fps)) seconds, \(width)x\(height): \(output.path)")
