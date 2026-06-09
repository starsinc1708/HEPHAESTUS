export function formatDuration(seconds: number): string {
	if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) {
		return '0s'
	}

	const total = Math.round(seconds)
	if (total === 0) return '0s'

	const h = Math.floor(total / 3600)
	const m = Math.floor((total % 3600) / 60)
	const s = total % 60

	const parts: string[] = []
	if (h > 0) parts.push(`${h}h`)
	if (m > 0) parts.push(`${m}m`)
	if (s > 0) parts.push(`${s}s`)

	return parts.join(' ')
}
