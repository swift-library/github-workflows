/// A greeting shared between modules.
public struct Greeting {
  /// The greeting's text.
  public let text: String

  /// Creates a greeting with the given text.
  public init(text: String) {
    self.text = text
  }
}
