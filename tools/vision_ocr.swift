// vision_ocr — 基于 macOS Vision 框架的中文 OCR 命令行工具
// 用法: vision_ocr <image> [--lang zh-Hans,en-US] [--level accurate|fast] [--json]
// 输出: --json 时输出 JSON（lines 数组，按阅读顺序 = 先上后下、先左后右）；否则逐行纯文本。
// 说明: 仅做识别，不做任何图像预处理（预处理由调用方在 Python 侧完成，便于做多轮比对）。

import Foundation
import Vision
import AppKit

var args = Array(CommandLine.arguments.dropFirst())
guard let imgPath = args.first else {
    FileHandle.standardError.write("usage: vision_ocr <image> [--lang ...] [--level ...] [--json]\n".data(using: .utf8)!)
    exit(2)
}
args.removeFirst()

var langs = ["zh-Hans", "en-US"]
var level = "accurate"
var asJSON = false
var i = 0
while i < args.count {
    switch args[i] {
    case "--lang":
        if i + 1 < args.count { langs = args[i + 1].split(separator: ",").map(String.init); i += 1 }
    case "--level":
        if i + 1 < args.count { level = args[i + 1]; i += 1 }
    case "--json":
        asJSON = true
    default:
        break
    }
    i += 1
}

guard let img = NSImage(contentsOfFile: imgPath),
      let tiff = img.tiffRepresentation,
      let rep = NSBitmapImageRep(data: tiff),
      let cg = rep.cgImage else {
    FileHandle.standardError.write("cannot load image: \(imgPath)\n".data(using: .utf8)!)
    exit(1)
}

let req = VNRecognizeTextRequest()
req.recognitionLevel = (level == "fast") ? .fast : .accurate
req.recognitionLanguages = langs
req.usesLanguageCorrection = true
req.automaticallyDetectsLanguage = false

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do { try handler.perform([req]) } catch {
    FileHandle.standardError.write("vision error: \(error)\n".data(using: .utf8)!)
    exit(1)
}

struct Payload: Encodable {
    let langs: [String]
    let level: String
    let lines: [Line]
}

struct Line: Encodable {
    let text: String
    let conf: Double
    let x: Double
    let y: Double   // 以图像左上角为原点的归一化坐标
    let w: Double
    let h: Double
}

var lines: [Line] = []
for obs in (req.results ?? []) {
    guard let cand = obs.topCandidates(1).first else { continue }
    let bb = obs.boundingBox           // 原点左下
    lines.append(Line(text: cand.string,
                      conf: Double(cand.confidence),
                      x: Double(bb.minX),
                      y: Double(1.0 - bb.maxY),
                      w: Double(bb.width),
                      h: Double(bb.height)))
}

func rowKey(_ l: Line) -> Int { Int(round(l.y * 1000)) }
lines.sort { a, b in
    if rowKey(a) != rowKey(b) { return rowKey(a) < rowKey(b) }
    return a.x < b.x
}

let enc = JSONEncoder()
enc.outputFormatting = [.withoutEscapingSlashes]
if asJSON {
    let data = try! enc.encode(Payload(langs: langs, level: level, lines: lines))
    print(String(data: data, encoding: .utf8)!)
} else {
    for l in lines { print(l.text) }
}
