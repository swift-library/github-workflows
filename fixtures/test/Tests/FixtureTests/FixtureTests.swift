import XCTest
@testable import Fixture

final class FixtureTests: XCTestCase {
  func testGreeting() {
    XCTAssertEqual(greeting(), "Incorrect greeting")
  }
}
