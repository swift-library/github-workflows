import XCTest
@testable import Fixture

final class FixtureTests: XCTestCase {
  func testGreeting() {
    #if os(Linux)
      XCTFail("Linux fixture")
    #endif
    XCTAssertEqual(greeting(), "Hello, workflows!")
  }
}
