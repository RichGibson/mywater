const VALID_QUALITY_RATINGS = ['good', 'off', 'bad'];
const VALID_EVENT_SUBTYPES = ['main_break', 'outage', 'boil_notice', 'other'];
const FREE_TEXT_MAX_LENGTH = 500;
const MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024;
const ALLOWED_PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/heic'];

const panel = document.getElementById('report-panel');
const form = document.getElementById('report-form');
const panelError = document.getElementById('report-panel-error');
const messageBox = document.getElementById('map-message');

function showMessage(text) {
  messageBox.textContent = text;
  messageBox.classList.add('visible');
  setTimeout(() => messageBox.classList.remove('visible'), 4000);
}

function updateFieldVisibility() {
  const reportType = document.getElementById('field-report-type').value;
  document.querySelectorAll('.field-quality').forEach((el) => {
    el.style.display = reportType === 'quality' ? '' : 'none';
  });
  document.querySelectorAll('.field-event').forEach((el) => {
    el.style.display = reportType === 'event' ? '' : 'none';
  });
}

function openReportPanel(selection) {
  if (window.mywaterCloseDetailPanel) window.mywaterCloseDetailPanel();
  panelError.textContent = '';
  form.reset();
  document.getElementById('field-parcel-id').value = selection.type === 'parcel' ? selection.id : '';
  document.getElementById('field-cluster-id').value = selection.type === 'cluster' ? selection.id : '';
  document.getElementById('field-obscured').value = selection.type === 'cluster' ? 'true' : 'false';
  const label = selection.type === 'parcel'
    ? `Reporting for parcel ${selection.apn}`
    : `Reporting for the area near ${selection.streetName} (anonymized)`;
  document.getElementById('report-panel-location').textContent = label;
  updateFieldVisibility();

  const photoField = document.querySelector('.field-photo');
  const photoNote = document.getElementById('field-photo-note');
  if (selection.type === 'cluster') {
    photoField.style.display = 'none';
    if (photoNote) photoNote.style.display = '';
  } else {
    photoField.style.display = '';
    if (photoNote) photoNote.style.display = 'none';
  }

  panel.classList.add('open');
}

function closeReportPanel() {
  panel.classList.remove('open');
}

function validateForm(formData) {
  const reportType = formData.get('report_type');
  const freeText = formData.get('free_text') || '';
  if (freeText.length > FREE_TEXT_MAX_LENGTH) {
    return `Description must be at most ${FREE_TEXT_MAX_LENGTH} characters.`;
  }
  if (reportType === 'event') {
    const eventSubtype = formData.get('event_subtype');
    if (!eventSubtype || !VALID_EVENT_SUBTYPES.includes(eventSubtype)) {
      return 'Please choose what kind of event this is.';
    }
  } else if (reportType === 'quality') {
    const taste = formData.get('taste');
    const smell = formData.get('smell');
    const color = formData.get('color');
    const pressure = formData.get('pressure');
    const hasRating = [taste, smell, color, pressure].some(
      (v) => v && VALID_QUALITY_RATINGS.includes(v)
    );
    if (!hasRating && !freeText.trim()) {
      return 'Please rate at least one thing (taste, smell, color, pressure) or describe the issue.';
    }
  }
  const photo = formData.get('photo');
  if (photo && photo.size > 0) {
    if (!ALLOWED_PHOTO_TYPES.includes(photo.type)) {
      return 'Photo must be a JPEG, PNG, or HEIC image.';
    }
    if (photo.size > MAX_PHOTO_SIZE_BYTES) {
      return 'Photo must be smaller than 5MB.';
    }
  }
  return null;
}

function stripEmptyOptionalFields(formData) {
  // Empty <select> values ("No opinion") and an empty file input still show
  // up as empty-string/empty-file FormData entries; the backend's Pydantic
  // model treats an empty string as "set to empty string", not "unset", for
  // fields like taste/smell/color/pressure/event_subtype — so send them only
  // when the user actually picked something.
  ['taste', 'smell', 'color', 'pressure', 'event_subtype', 'free_text'].forEach((key) => {
    if (formData.get(key) === '') formData.delete(key);
  });
  const photo = formData.get('photo');
  if (photo && photo.size === 0) formData.delete('photo');
  // Defense in depth: the photo field is hidden for obscured reports, but a
  // stale selection from before switching to obscure mode could still leave
  // a value in the FormData, so drop it explicitly for obscured submissions.
  if (formData.get('obscured') === 'true') formData.delete('photo');
  if (formData.get('report_type') === 'quality') {
    formData.delete('event_subtype');
    formData.delete('ongoing');
  }
  if (formData.get('report_type') === 'event') {
    ['taste', 'smell', 'color', 'pressure'].forEach((key) => formData.delete(key));
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  panelError.textContent = '';

  const formData = new FormData(form);
  const clientError = validateForm(formData);
  if (clientError) {
    panelError.textContent = clientError;
    return;
  }
  stripEmptyOptionalFields(formData);

  const submitButton = form.querySelector('button[type="submit"]');
  submitButton.disabled = true;

  try {
    const resp = await fetch('/api/reports', {
      method: 'POST',
      body: formData,
    });
    if (resp.ok) {
      closeReportPanel();
      showMessage('Thanks — your report has been posted.');
      if (window.mywaterRefreshReports) window.mywaterRefreshReports();
    } else {
      const body = await resp.json().catch(() => ({}));
      panelError.textContent = body.detail || 'Something went wrong submitting your report. Please try again.';
    }
  } catch (err) {
    panelError.textContent = 'Could not reach the server. Check your connection and try again.';
  } finally {
    submitButton.disabled = false;
  }
});

document.getElementById('field-report-type').addEventListener('change', updateFieldVisibility);
document.getElementById('report-panel-close').addEventListener('click', closeReportPanel);

window.mywaterOpenReportPanel = openReportPanel;
window.mywaterShowMessage = showMessage;
window.mywaterCloseReportPanel = closeReportPanel;
