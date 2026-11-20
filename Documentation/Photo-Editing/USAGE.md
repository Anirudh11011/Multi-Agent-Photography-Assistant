# Photo Editing: Usage

## Attaching a photo

**+ → Image upload** (JPG, PNG, WebP). A preview appears above the input bar with:

| Control | When it shows | What it does |
|---|---|---|
| **Auto-improve** | Whenever a photo is attached | The analyst decides and applies the edits. |
| **Reset to original** | After at least one edit | The next edit starts from the photo as uploaded. |
| **Remove image** | Before the first message about the photo | Detaches it (unchanged behaviour). |

After an edit the preview thumbnail shows the edited version and the name reads
"*name* · edited", because that is what the next edit will start from.

## Instructed edits

Type what you want. Examples that are routed to the editor:

- `increase the brightness by 10% and contrast by 20%`
- `make it a little warmer`
- `crop it to 4:5 for Instagram`
- `straighten the horizon, it tilts about 2 degrees to the right`
- `recover the sky and lift the shadows`
- `make it black and white` (saturation −100)
- `a bit brighter still` (after an earlier edit; stacks on it)

Examples that are **not** edits and get an answer about the photo instead:

- `what's in this photo?`
- `how could I make this better next time?`
- `why is it blurry?`

## AI edit (Auto-improve)

Press **Auto-improve**. The user bubble reads "Auto-improve this photo". The analyst
fixes what it can see is wrong (exposure, crushed shadows, blown highlights, colour cast,
tilt) and adds modest enhancement, aiming for a natural result. If the photo is already
good, it says so and changes nothing.

## The answer

```
I'm lifting the crushed foreground, warming the blue cast and adding a touch of
saturation and sharpening.

Edits applied
- Tone: shadows +20
- White balance: temperature +10 (warmer)
- Saturation +10%
- Sharpen amount 0.5, radius 1 px

[ Before ]  [ After ]
[ Download edited photo ]
```

- The **Edits applied** list is what was actually applied to the pixels.
- If you asked for something the tools can't do (remove a person, replace the sky), it
  is listed under **Not possible with the editing tools** rather than faked.
- **Download edited photo** gives a full-resolution JPEG (long edge up to 4096 px).
- **How this answer was reached** shows the router's decision, the analyst's full plan,
  and every tool call with its arguments and result.

## Timing (measured during development)

| Turn | Time |
|---|---|
| Instructed edit (2 edits) | ~3 s |
| Auto-improve (4 edits) | ~30 s, mostly the vision model reasoning about the photo |
| Question about the photo | unchanged, plus one short routing call |
