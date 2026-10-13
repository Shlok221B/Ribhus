#!/usr/bin/env swift
/**
 * One-shot macOS CoreLocation fix for Ribhus.
 * Prints one JSON line: {"lat":..,"lng":..,"accuracy_m":..} or {"error":"..."}.
 * First run may prompt for Location Services permission (System Settings).
 */
import Foundation
import CoreLocation

final class Locator: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private let lock = NSLock()
    private var finished = false
    private var payload = #"{"error":"timeout"}"#

    func run(timeoutSeconds: Double) {
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        let status = manager.authorizationStatus
        if status == .notDetermined {
            manager.requestWhenInUseAuthorization()
        } else if status == .denied || status == .restricted {
            emit(#"{"error":"location_denied"}"#)
            return
        } else {
            manager.requestLocation()
        }
        RunLoop.current.run(until: Date().addingTimeInterval(timeoutSeconds))
        emit(payload)
    }

    private func emit(_ json: String) {
        lock.lock()
        defer { lock.unlock() }
        if finished { return }
        finished = true
        payload = json
        fputs(json + "\n", stdout)
        fflush(stdout)
        // Stop run loop soon
        CFRunLoopStop(CFRunLoopGetMain())
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse:
            manager.requestLocation()
        case .denied, .restricted:
            emit(#"{"error":"location_denied"}"#)
        default:
            break
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let c = locations.last else { return }
        let json = String(
            format: #"{"lat":%.6f,"lng":%.6f,"accuracy_m":%.1f}"#,
            c.coordinate.latitude,
            c.coordinate.longitude,
            max(c.horizontalAccuracy, 0)
        )
        emit(json)
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        let msg = error.localizedDescription
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        emit("{\"error\":\"\(msg)\"}")
    }
}

let locator = Locator()
locator.run(timeoutSeconds: 12)
