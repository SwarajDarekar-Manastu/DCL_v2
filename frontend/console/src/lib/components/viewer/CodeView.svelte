<script lang="ts">
	interface Props {
		language: string;
		firstLine: number;
		lines: string[];
		highlight: [number, number] | null;
	}

	let { language, firstLine, lines, highlight }: Props = $props();
	const lit = (n: number) => highlight !== null && n >= highlight[0] && n <= highlight[1];
</script>

<figure class="bg-background m-0 overflow-hidden rounded-md border">
	<figcaption class="text-muted-foreground border-b px-3 py-1.5 font-mono text-xs">{language}</figcaption>
	<pre class="m-0 overflow-x-auto py-2 font-mono text-[13px] leading-6"><code
			>{#each lines as line, i (i)}<span
					class="line block pr-4 [&.lit]:bg-info-bg [&.lit]:shadow-[inset_2px_0_0_var(--info)]"
					class:lit={lit(firstLine + i)}
					data-line={firstLine + i}
					><span class="text-muted-foreground num inline-block w-14 pr-4 text-right select-none">{firstLine + i}</span>{line}
</span>{/each}</code
		></pre>
</figure>
