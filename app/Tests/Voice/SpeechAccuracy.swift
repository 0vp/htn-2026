import Foundation

/// Word-level Levenshtein distance. Punctuation and case do not count as ASR errors.
enum SpeechAccuracy {
    static func words(_ text: String) -> [String] {
        text.lowercased().split { !$0.isLetter && !$0.isNumber }.map(String.init)
    }
    static func errorRate(reference: String, hypothesis: String) -> Double {
        let expected = words(reference), actual = words(hypothesis)
        guard !expected.isEmpty else { return actual.isEmpty ? 0 : 1 }
        var previous = Array(0...actual.count)
        for (i, word) in expected.enumerated() {
            var next = [i + 1]
            for (j, other) in actual.enumerated() {
                next.append(min(previous[j + 1] + 1, next[j] + 1, previous[j] + (word == other ? 0 : 1)))
            }
            previous = next
        }
        return Double(previous.last!) / Double(expected.count)
    }
}
