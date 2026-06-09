import { describe, it, expect } from 'vitest'
import { formatDuration } from '@/utils/duration'

describe('formatDuration', () => {
	it('returns "0s" for 0', () => {
		expect(formatDuration(0)).toBe('0s')
	})

	it('returns "5s" for 5', () => {
		expect(formatDuration(5)).toBe('5s')
	})

	it('returns "1m 5s" for 65', () => {
		expect(formatDuration(65)).toBe('1m 5s')
	})

	it('returns "1h 1m 1s" for 3661', () => {
		expect(formatDuration(3661)).toBe('1h 1m 1s')
	})

	it('drops zero parts (90 → "1m 30s")', () => {
		expect(formatDuration(90)).toBe('1m 30s')
	})

	it('drops zero parts (3600 → "1h")', () => {
		expect(formatDuration(3600)).toBe('1h')
	})

	it('returns "0s" for negative values', () => {
		expect(formatDuration(-5)).toBe('0s')
	})

	it('returns "0s" for NaN', () => {
		expect(formatDuration(NaN)).toBe('0s')
	})

	it('rounds fractional seconds to integer', () => {
		expect(formatDuration(1.7)).toBe('2s')
		expect(formatDuration(59.3)).toBe('59s')
		expect(formatDuration(119.9)).toBe('2m')
	})

	it('returns "0s" for Infinity', () => {
		expect(formatDuration(Infinity)).toBe('0s')
	})
})
