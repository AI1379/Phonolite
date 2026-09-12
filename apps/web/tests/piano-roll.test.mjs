import assert from "node:assert/strict";
import test from "node:test";
import { beatSeconds, secondsBeat, rulerBars, pitchLabel } from "../src/components/pianoRollLayout.ts";
import { alignedValue } from "../src/components/referenceAlignment.ts";

test("the ruler retains global bars and excludes an exact end boundary", () => {
  assert.deepEqual(rulerBars([], 4, 8), [{ number: 2, start: 4, end: 8, meter: "4/4" }]);
  assert.deepEqual(rulerBars([], 6, 10).map(({number, start, end}) => [number, start, end]), [[2, 4, 8], [3, 8, 10]]);
});

test("compound meter and a later change keep quarter-note beat positions", () => {
  const meters = [{ beat: 0, numerator: 9, denominator: 8 }, { beat: 9, numerator: 3, denominator: 4 }];
  assert.deepEqual(rulerBars(meters, 4, 12).map(({number, start, end}) => [number, start, end]), [[1, 0, 4.5], [2, 4.5, 9], [3, 9, 12]]);
});

test("a mid-bar meter change closes the partial bar", () => {
  const meters = [{ beat: 6, numerator: 3, denominator: 4 }];
  assert.deepEqual(rulerBars(meters, 0, 9).map(({number, start, end}) => [number, start, end]), [[1, 0, 4], [2, 4, 6], [3, 6, 9]]);
});

test("playback seconds and display beats agree on both sides of tempo changes", () => {
  const tempos = [{ beat: 0, bpm: 120 }, { beat: 4, bpm: 60 }, { beat: 6, bpm: 180 }];
  for (const [beat, seconds] of [[0, 0], [2, 1], [4, 2], [5, 3], [6, 4], [7.5, 4.5]]) {
    assert.ok(Math.abs(beatSeconds(tempos, beat) - seconds) < 1e-9);
    assert.ok(Math.abs(secondsBeat(tempos, seconds) - beat) < 1e-9);
  }
  assert.equal(secondsBeat([], 3), 6);
  assert.equal(beatSeconds([], 6), 3);
});

test("octave labels match standard MIDI pitches", () => {
  assert.equal(pitchLabel(21), "A0");
  assert.equal(pitchLabel(60), "C4");
  assert.equal(pitchLabel(108), "C8");
});

test("reference alignment honors source lead-in and variable tempo", () => {
  const anchors = [{seconds:2,beat:0},{seconds:6,beat:8},{seconds:10,beat:12}];
  assert.equal(alignedValue(anchors,4,"beat"),4);
  assert.equal(alignedValue(anchors,10,"beat"),8);
  assert.equal(alignedValue(anchors,8,"seconds"),10);
});

test("unmarked source time cannot silently become a score selection", () => {
  const anchors = [{seconds:2,beat:0},{seconds:6,beat:8}];
  assert.equal(alignedValue(anchors,1,"seconds"),null);
  assert.equal(alignedValue(anchors,10,"beat"),null);
  assert.equal(alignedValue([],1,"seconds"),null);
});
