// State fed by the layout's single live channel (backend/api/ws.py); pages read it instead of opening sockets.

import type { LiveEvent, LiveStatus } from '$lib/api_endpoint';

class LiveState {
	status = $state<LiveStatus>('closed');
	/** ops counter "review_counts" published by the review backend */
	reviewCounts = $state<{ hard: number; soft: number } | null>(null);
	/** last "case" event; pages react to it and refetch what they show */
	lastCaseEvent = $state<LiveEvent | null>(null);
	/** last "run" event (benchmark run progress); run pages refetch on it */
	lastRunEvent = $state<LiveEvent | null>(null);
}

export const live = new LiveState();

export function applyLiveEvent(event: LiveEvent): void {
	if (event.topic === 'ops' && event.key === 'review_counts') {
		live.reviewCounts = { hard: Number(event.data.hard ?? 0), soft: Number(event.data.soft ?? 0) };
	} else if (event.topic === 'case') {
		live.lastCaseEvent = event;
	} else if (event.topic === 'run') {
		live.lastRunEvent = event;
	}
}
