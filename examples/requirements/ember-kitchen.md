# Ember Kitchen — a cooking video school

Ember Kitchen teaches home cooks through short video lessons. Instructors publish lessons; learners watch them,
keep track of what they have finished and ask questions under a lesson.

## What the app holds

- **Courses**: a title, a short summary, a cover image, a cuisine (Japanese, Italian, Mexican, Indian, French), a
  level (beginner, intermediate, advanced) and the instructor who runs it.
- **Lessons** belong to a course: a title, a description, the lesson video, a poster image, the duration in seconds
  (filled from the uploaded video), a topic (knife skills, sauces, baking, grilling, plating) and a status: a lesson
  is a draft until the instructor publishes it; a published lesson can be archived.
- **Captions** belong to a lesson: a subtitle file and its language (English or Japanese); every lesson should offer
  captions in both languages.
- **Questions**: a learner asks a question under a lesson (a text); the question is open until the instructor
  answers it (an answer text) and marks it answered. Learners see only their own questions; instructors see all.
- **Progress**: a learner marks a lesson as watched (one record per learner and lesson, never twice).

## People

Two kinds of people sign in: **instructors**, who create courses and lessons, upload videos and captions, publish
lessons and answer questions; and **learners**, who browse published lessons, watch them with captions, mark them
watched and ask questions. Learners never see draft lessons.

## Look

Dark first, like a cinema: quiet charcoal surfaces where the video stills carry the colour, a warm amber accent for
buttons and links, bold geometric headings. Pictures and videos large: people pick a lesson by its still.
