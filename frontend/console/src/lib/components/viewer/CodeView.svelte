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

<figure>
	<figcaption>{language}</figcaption>
	<pre><code
			>{#each lines as line, i (i)}<span class="line" class:lit={lit(firstLine + i)} data-line={firstLine + i}
					><span class="no">{firstLine + i}</span>{line}
</span>{/each}</code
		></pre>
</figure>

<style>
	figure {
		margin: 0;
	}
	figcaption {
		font-size: 0.8rem;
		opacity: 0.7;
	}
	pre {
		background: var(--surface);
		border: 1px solid var(--border);
		padding: 0.5rem 0;
		overflow-x: auto;
		font-size: 0.85rem;
	}
	.line {
		display: block;
		padding-right: 1rem;
	}
	.no {
		display: inline-block;
		width: 3.5rem;
		padding-right: 0.75rem;
		text-align: right;
		opacity: 0.5;
		user-select: none;
	}
	.lit {
		background: rgb(245 158 11 / 0.25);
	}
</style>
