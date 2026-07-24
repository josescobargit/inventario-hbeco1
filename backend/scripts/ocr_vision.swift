import Foundation
import Vision
import ImageIO

guard CommandLine.arguments.count >= 3 else {
    FileHandle.standardError.write(Data("usage: ocr_vision.swift IMAGE ORIENTATION\n".utf8))
    exit(2)
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
let rawOrientation = UInt32(CommandLine.arguments[2]) ?? 1
guard let orientation = CGImagePropertyOrientation(rawValue: rawOrientation) else {
    FileHandle.standardError.write(Data("invalid orientation\n".utf8))
    exit(2)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["es-EC", "es-ES", "en-US"]

do {
    let handler = VNImageRequestHandler(url: imageURL, orientation: orientation)
    try handler.perform([request])
    let observations = request.results ?? []
    let ordered = observations.sorted {
        if abs($0.boundingBox.midY - $1.boundingBox.midY) > 0.015 {
            return $0.boundingBox.midY > $1.boundingBox.midY
        }
        return $0.boundingBox.minX < $1.boundingBox.minX
    }
    for observation in ordered {
        if let candidate = observation.topCandidates(1).first {
            print(candidate.string)
        }
    }
} catch {
    FileHandle.standardError.write(Data("vision_error: \(error)\n".utf8))
    exit(1)
}
