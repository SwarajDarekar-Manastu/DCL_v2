<script lang="ts">
	// Small status pill. Status colors are reserved for severity and outcome; "neutral" is the default look.
	import type { Snippet } from 'svelte';
	import { cn } from '$lib/utils';

	export type Tone = 'hard' | 'warn' | 'ok' | 'info' | 'neutral' | 'outline';

	interface Props {
		tone?: Tone;
		children: Snippet;
		class?: string;
		title?: string;
	}

	let { tone = 'neutral', children, class: className, title }: Props = $props();
	const STYLE: Record<Tone, string> = {
		hard: 'bg-hard-bg text-hard border-hard-border',
		warn: 'bg-warn-bg text-warn border-warn-border',
		ok: 'bg-ok-bg text-ok border-ok-border',
		info: 'bg-info-bg text-info border-info-border',
		neutral: 'bg-muted text-muted-foreground border-transparent',
		outline: 'border-border text-foreground'
	};
</script>

<span
	{title}
	class={cn(
		'inline-flex h-5 shrink-0 items-center gap-1 rounded-md border px-1.5 text-[11px] font-medium whitespace-nowrap',
		STYLE[tone],
		className
	)}
>
	{@render children()}
</span>
