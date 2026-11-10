# Story 33.10 — Learning platform

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47 · **Depends on:** 33.5, 33.7

## User story

As a learner I want to enroll in a course, pick up where I left off, take quizzes and see my progress; as an
instructor I want to build a course from lessons, so that the app works like a real learning platform.

## Context

- The `learning` archetype has no pattern yet (Epic 32 left it `back-office`); this domain gives it one.
- Reuses comments (lesson discussion) and the media players (Epic 29) for video lessons.

## Steps

1. **Domain** `templates/domains/learning/`: roles `course` (title, summary, cover, level, instructor), `lesson` (in a
   course, ordered, a video or text body, duration), `instructor`; areas Learners (pattern `learning`, new), Instructors
   (a studio, `back-office`), Admin; required features enrollment and progress; optional quiz, discussion, reviews,
   certificates.
2. **Features**:
   - `enrollment` (`attachesTo: course`): enroll (free, or paid through the payments plugin), `enrolledByMe`,
     `progress` (the share of lessons done), `lastLesson`; mark a lesson complete (also automatically at the end of a
     video); "My learning" with Resume;
   - `quiz` (`attachesTo: lesson`): questions (single or multiple choice), attempts, score, pass mark, the answers
     shown after submitting;
   - `reviews` (`attachesTo: course`, shared later with e-commerce): stars and text from enrolled learners,
     `rating`, `reviewCount`;
   - `certificates`: issued when progress reaches 100% and quizzes pass; a printable page.
3. **Types**:
   - **course catalogue** (self-paced): home with Continue learning and categories; the course page (what you'll
     learn, curriculum by section, instructor, reviews, Enroll); the lesson player (curriculum beside the lesson,
     Mark complete, Next lesson, discussion under it);
   - **classroom** (cohorts): classes with a schedule, assignments with due dates and submissions, grades.
4. **The `learning` pattern** (Epic 32's kind) added for the Learners area.
5. **The reference requirement** generated end to end and its tasks passing.

## Acceptance criteria

- [x] A learner enrolls, resumes the last lesson from home in one click, completes a lesson, passes a quiz and sees
      their progress move; an instructor adds a lesson to a course.

## Verify

`make domain-check NAME=learning`, `make test`, `make kit-test`, the real run in the UI.

## Status

Proposed 2026-11-10.

**Done 2026-11-10 (with deviations).** `templates/domains/learning` (roles course and lesson; learners `catalogue`,
instructors and admins `back-office`) with three features: **enrollment** (an `<Course>Enrollment` per learner,
`myEnrollmentId`, `enrollmentCount`, an Enroll toggle), **completion** (a `<Lesson>Completion`, `myCompletionId` on the
lesson, and on the course `myCompletedCount` (only the caller's rows) and `lessonCount` (computed fields may sit on
another entity: `target`), a "Mark complete" toggle sending the lesson's course), and comments on the lesson. The type
`course-catalogue` puts `AppResume` (Continue, with the progress bar) first on the learners' home. The real v10 draft
merged all three and passes **5 of 5** tasks (baseline 2).

Deviations: quizzes, reviews and certificates stay the model's entities; the classroom type is not built; the
`learning` pattern is not added (the area uses `catalogue`).
