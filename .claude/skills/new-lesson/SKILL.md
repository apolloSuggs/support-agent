---
name: new-lesson
description: Run the full routine whenever the user opens, pastes or finishes a Dev Compass course lesson (or says "lesson N"). Writes the course note, builds the matching piece in the support-agent project, publishes the interactive lesson page, quizzes, and records progress, without the user having to ask for each part.
---

# New course lesson: do all of this, unprompted

The user is taking the Dev Compass course and building this project alongside it. They should never have to ask for the artifacts, the note, or the build. When a lesson arrives (pasted text, "lesson N is open", a video link), work through every step and report in a short list at the end.

## Steps
1. **Read the lesson.** Pasted text first. Otherwise Chrome (the user has approved this for lessons they have unlocked; never open locked ones). Video-only lessons: say so, and ask for a paste of the walkthrough or transcript.
2. **Course note.** Write `certification/course-notes/lesson-N.md` (paraphrase, no copied text, no quiz answers) and add the line to that folder's README index.
3. **Map to the exam.** Read `certification/COURSE-CROSSWALK.md` and the matching `STUDY.md`. Check the guide first. Where the course differs from the guide (names, base API vs SDK, prompt-JSON vs tool schema), say so.
4. **Build alongside.** If the lesson's topic is missing from this project (a coordinator, a session fork, scratchpad files...), build it in the project now with the Claude Agent SDK. Do not skip it, and do not patch around it. The course exercise code is for the user; the project gets the real equivalent. Keep it small, run it, show the result.
5. **Lesson page.** Publish an interactive artifact for the lesson (or a pair of linked lessons) from `certification/lesson-pages/`, same URL on updates: plain-English explanation, every new term defined, a diagram, a "guide vs course vs ours" box, a short quiz, a one-page summary. Add it to `lesson-pages/README.md`. Give the user the link.
6. **Quiz** in chat. First serve any guide sample questions that just became ready (`certification/SAMPLE-QUESTIONS.md`, paraphrased, one at a time, then fill in the Result column). Then add 3-4 scenario questions of our own (AskUserQuestion, one at a time). Only on material already taught. Explain wrong options.
7. **Record.** Tick the `STUDY.md` boxes, update the tracker in `certification/README.md`, update the Study Map artifact (its `COURSE_DONE` number and task cards), update `CLAUDE.md` file list if files were added.
8. **Final message:** short. What was built, the page link, what is open, one next step.

## Rules
- The user does course exercises themselves. Never give answers first.
- Define acronyms and new terms the first time. Dates MM-DD-YYYY. Never read or print `.env`.
- Keep messages short and in order; the user gets overwhelmed by too much at once.
- Never make the user repeat an instruction that is written here.
