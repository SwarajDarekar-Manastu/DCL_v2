<script lang="ts">
	// A large guide that opens over the Rules page: the idea, how to make a rule, what you get, how to manage it.
	// Real screenshots from the Console on test data (asset/rules-guide), one step at a time.
	import { Dialog } from 'bits-ui';
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';
	import ArrowRightIcon from '@lucide/svelte/icons/arrow-right';
	import BookOpenIcon from '@lucide/svelte/icons/book-open';
	import CheckIcon from '@lucide/svelte/icons/check';
	import XIcon from '@lucide/svelte/icons/x';
	import { Button } from '$lib/components/ui/button';
	import { GUIDE_INTRO, GUIDE_STEPS, GUIDE_TITLE } from './rules_guide';

	let { open = $bindable(false) }: { open?: boolean } = $props();
	let index = $state(0);
	let step = $derived(GUIDE_STEPS[index]);
	let last = $derived(index === GUIDE_STEPS.length - 1);

	$effect(() => {
		if (open) index = 0;
	});
</script>

<Button variant="outline" size="sm" onclick={() => (open = true)}><BookOpenIcon />{GUIDE_TITLE}</Button>

<Dialog.Root bind:open>
	<Dialog.Portal>
		<Dialog.Overlay class="fixed inset-0 z-50 bg-black/60" />
		<Dialog.Content
			class="bg-background text-foreground fixed top-1/2 left-1/2 z-50 grid h-[min(52rem,calc(100vh-2rem))] w-[min(70rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-xl border shadow-2xl outline-none"
		>
			<header class="flex items-start justify-between gap-4 border-b px-6 py-4">
				<div class="grid gap-1">
					<Dialog.Title class="m-0 text-lg font-semibold">{GUIDE_TITLE}</Dialog.Title>
					<Dialog.Description class="text-muted-foreground m-0 text-sm">{GUIDE_INTRO}</Dialog.Description>
				</div>
				<Dialog.Close class="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex size-8 items-center justify-center rounded-md focus-visible:ring-2 focus-visible:outline-none" aria-label="Close the guide">
					<XIcon class="size-4" aria-hidden="true" />
				</Dialog.Close>
			</header>

			<div class="grid min-h-0 md:grid-cols-[15rem_minmax(0,1fr)]">
				<nav class="hidden overflow-y-auto border-r p-3 md:block" aria-label="Guide steps">
					<ol class="m-0 grid list-none gap-1 p-0">
						{#each GUIDE_STEPS as s, i (s.id)}
							<li>
								<button
									type="button"
									class={[
										'hover:bg-muted flex w-full items-start gap-2 rounded-md px-2.5 py-2 text-left text-[13px] leading-snug transition-colors',
										i === index && 'bg-muted font-medium'
									]}
									aria-current={i === index ? 'step' : undefined}
									onclick={() => (index = i)}
								>
									<span class={['mt-px inline-flex size-5 shrink-0 items-center justify-center rounded-full border text-[11px]', i < index && 'bg-foreground text-background border-transparent']}>
										{#if i < index}<CheckIcon class="size-3" aria-hidden="true" />{:else}{i + 1}{/if}
									</span>
									{s.title}
								</button>
							</li>
						{/each}
					</ol>
				</nav>

				<section class="min-h-0 overflow-y-auto p-6" aria-live="polite" aria-label="Step {index + 1} of {GUIDE_STEPS.length}">
					<div class="grid gap-5">
						<div class="grid gap-1.5">
							<p class="text-muted-foreground m-0 text-xs font-medium tracking-wide uppercase">Step {index + 1} of {GUIDE_STEPS.length}</p>
							<h3 class="m-0 text-xl leading-tight font-semibold">{step.title}</h3>
						</div>
						<div class="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,17rem)]">
							<div class="grid gap-3">
								<p class="m-0 text-[15px] leading-relaxed">{step.summary}</p>
								<ul class="m-0 grid list-disc gap-1.5 pl-5 text-sm leading-relaxed">
									{#each step.points as point (point)}<li>{point}</li>{/each}
								</ul>
							</div>
							<p class="bg-muted/60 m-0 rounded-md border px-3 py-2.5 text-sm"><strong>What you get.</strong> {step.get}</p>
						</div>
						{#each step.images as image (image.src)}
							<figure class="m-0 grid gap-2">
								<a href={image.src} target="_blank" rel="noopener noreferrer" title="Open full size">
									<img class="w-full rounded-lg border" src={image.src} alt={image.alt} />
								</a>
								<figcaption class="text-muted-foreground text-xs">{image.caption} Click the picture to open it full size.</figcaption>
							</figure>
						{/each}
					</div>
				</section>
			</div>

			<footer class="flex items-center justify-between gap-3 border-t px-6 py-3">
				<Button variant="ghost" size="sm" disabled={index === 0} onclick={() => (index -= 1)}><ArrowLeftIcon />Back</Button>
				<div class="flex gap-1.5" aria-hidden="true">
					{#each GUIDE_STEPS as s, i (s.id)}<span class={['size-1.5 rounded-full', i === index ? 'bg-foreground' : 'bg-border']}></span>{/each}
				</div>
				{#if last}
					<Button size="sm" onclick={() => (open = false)}>Got it</Button>
				{:else}
					<Button size="sm" onclick={() => (index += 1)}>Next<ArrowRightIcon /></Button>
				{/if}
			</footer>
		</Dialog.Content>
	</Dialog.Portal>
</Dialog.Root>
