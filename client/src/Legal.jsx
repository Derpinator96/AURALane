import { Link } from "react-router-dom";

// The privacy and terms pages. Readable without signing in. Every statement
// here describes what the code in this repository does; where something is
// planned rather than built, the page says so.

export function Footer() {
  return (
    <footer className="foot">
      <span>AURALane proof of concept. Not a medical device.</span>
      <Link to="/privacy">Privacy</Link>
      <Link to="/terms">Terms</Link>
    </footer>
  );
}

export function Privacy() {
  return (
    <main className="legal">
      <h1>Privacy</h1>
      <p className="note">Written by the AURALane team (Team Peanut Butter, NIT Raipur) for the Precision Care Challenge 2026 proof of concept. It describes this build, not a deployed service.</p>

      <h2>No real patient data</h2>
      <p>
        This build holds only public, openly licensed or synthetic images: chest X-rays from NIH
        ChestX-ray14 and brain MRI from BraTS 2021. Patient names and IDs attached to them are
        generated and marked as synthetic (for example <span className="mono">SIM^PATIENT^0042</span>).
        Do not upload real patient data.
      </p>

      <h2>What never leaves the hospital</h2>
      <p>
        In the intended deployment, de-identification runs inside the hospital before anything is
        sent. Names, patient IDs, dates of birth, institution names and free-text fields are removed
        or replaced with pseudonyms, following the DICOM PS3.15 basic confidentiality profile. Every
        study and series ID is replaced consistently. Private tags and overlay planes are deleted.
        Text drawn into the image pixels is found by OCR and blacked out.
      </p>
      <p>
        The table that links a pseudonym back to the real patient (the identity map) stays in the
        hospital. The shared system only ever sees pseudonyms. In this proof of concept both run on
        one machine, and the identity map is a local file.
      </p>
      <p>
        Limit: OCR masking is high-recall, not perfect. The failure mode is a name drawn into the
        pixels surviving masking. That is why chest X-ray, which rarely carries burned-in text, is
        the first modality, with human review of a sample of studies.
      </p>

      <h2>What is stored, and where</h2>
      <table className="admin">
        <thead><tr><th>What</th><th>Where (local build)</th><th>Where (AWS, planned, not built)</th></tr></thead>
        <tbody>
          <tr><td>De-identified images</td><td>Orthanc</td><td>AWS HealthImaging, us-east-1</td></tr>
          <tr><td>Worklist rows: pseudonymous patient ID, study IDs, lane, findings signals, model ID, arrival time, verdict</td><td>DynamoDB Local</td><td>Amazon DynamoDB</td></tr>
          <tr><td>Audit events: who acted, what, when, on which study</td><td>DynamoDB Local</td><td>Amazon DynamoDB</td></tr>
          <tr><td>Triage rationale images (Grad-CAM, tumour outline)</td><td>Local files</td><td>Amazon S3</td></tr>
          <tr><td>Identity map (pseudonym to patient)</td><td>Local file</td><td>Stays in the hospital</td></tr>
        </tbody>
      </table>
      <p>
        HealthImaging is not offered in India. Under the plan above, only de-identified data would be
        stored outside the country; that is a data-residency question under the DPDP Act that a real
        deployment has to answer first.
      </p>

      <h2>How long</h2>
      <p>
        A temporary copy of each cleaned study is deleted as soon as it is imported, including when
        processing fails. No retention period is implemented for anything else in this build: images,
        worklist rows and rationale images stay until an operator deletes them. The audit log is
        append only by design; nothing in the application can edit or delete an entry.
      </p>

      <h2>In your browser</h2>
      <p>
        Signing in stores a token in this tab's session storage. It expires after one hour and is
        removed when you sign out or close the tab. Links to rationale images expire after five
        minutes. There are no cookies, no analytics and no third-party requests: fonts are served
        with the app.
      </p>

      <h2>Non-diagnostic</h2>
      <p>
        AURALane puts studies in a reading order. It does not diagnose, and it never says what is in
        a study. A radiologist reads every study.
      </p>
    </main>
  );
}

export function Terms() {
  return (
    <main className="legal">
      <h1>Terms</h1>
      <p className="note">Written by the AURALane team, not by a lawyer. They describe how this proof of concept may be used.</p>

      <h2>What this is</h2>
      <p>
        A proof of concept built for the Precision Care Challenge 2026. It orders a radiology reading
        queue. It is not a medical device, is not cleared or approved by any regulator, and must not
        be used to make or delay a clinical decision.
      </p>

      <h2>Decision support only</h2>
      <p>
        Lanes, acuity scores and triage rationale images are aids to ordering a queue. They are not
        findings. When the model is not confident enough it assigns no lane, and a person must place
        the study. Every study is read by a radiologist.
      </p>

      <h2>Data you may use</h2>
      <p>
        Only public, openly licensed or synthetic images. Do not upload images or records of real
        patients. The development sign-in is for local use; it protects a laptop, not patient data.
      </p>

      <h2>No warranty</h2>
      <p>
        Provided as is, without warranty of any kind. The model outputs have not been clinically
        validated, and the known limits are written up in the repository's documentation.
      </p>

      <h2>Source and datasets</h2>
      <p>
        Source code: <a className="ul" href="https://github.com/Derpinator96/AURALane">github.com/Derpinator96/AURALane</a>.
        The datasets keep their own licences: NIH ChestX-ray14, BraTS 2021, and the TorchXRayVision
        and MONAI model weights.
      </p>
    </main>
  );
}
