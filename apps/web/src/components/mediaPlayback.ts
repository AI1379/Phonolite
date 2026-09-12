// One audible source at a time across reference video/audio and score previews.
export function pauseOtherMedia(active: HTMLMediaElement): void {
  document.querySelectorAll<HTMLMediaElement>("audio,video").forEach((player) => {
    if (player !== active) player.pause();
  });
}
