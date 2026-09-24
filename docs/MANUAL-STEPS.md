# Manual steps: only you can do these

Ordered by urgency. **Steps 1–4 involve waiting on someone else, so start them
today, in this order,** and do the rest while you wait. After each step, re-run:

```
.venv\Scripts\python scripts\doctor.py
```

| # | step | waiting period | hands-on | turns green in doctor |
|---|---|---|---|---|
| 1 | AWS account | activation: minutes, up to 24 h | 15 min |: (enables 2, 3, 5) |
| 2 | Bedrock model access, us-east-1 | approval: minutes to days | 5 min |: |
| 3 | Lambda + SageMaker quotas | increase requests: hours to days | 10 min |: |
| 4 | BraTS cases | registration + large download | 15–60 min | `brats` |
| 5 | AWS CLI, IAM user, `aws configure` | none | 15 min | `aws` |
| 6 | Docker Desktop | none | 15–30 min | `docker` (then `orthanc`, `dynamodb` via Task 5) |
| 7 | Tesseract OCR + PATH | none | 5 min | `tesseract` |
|: | NIH PNGs | **already done**: 5,606 in `images/` |: | `nih pngs` |

Already done for you: Python 3.14 venv in `.venv\` with all 24 packages (CPU torch),
Node v24, WSL2 with Ubuntu.

---

## 1. AWS account: start now, activation can take up to 24 h

1. https://aws.amazon.com → **Create an AWS Account**. Needs a card and phone
   verification. Pick the **Basic (free)** support plan.
2. Activation is usually minutes but can take up to 24 h. Steps 2 and 3 need it.
3. As soon as you can sign in, do these two (5 min, and they protect you):
   - **MFA on the root user**: IAM → *Root user* → *Assign MFA device*.
   - **A budget alert**: Billing → *Budgets* → *Create budget* → *Monthly cost
     budget*, e.g. $20, with your email. A forgotten SageMaker endpoint bills by the
     hour; this is how you find out on day one instead of at month end.

Never create access keys for the root user. Step 5 makes a separate user for that.

## 2. Bedrock model access in us-east-1: start as soon as step 1 activates

Approval is not instant, so submit this before anything else.

1. Console, region selector (top right) → **US East (N. Virginia) us-east-1**.
   Access is per region; granting it in Mumbai does nothing here.
2. Amazon Bedrock → **Model access** (left nav) → *Modify model access* → tick the
   models the PoC will call → *Next* → *Submit*.
3. For **Anthropic** models you'll be asked for use-case details once. This is
   the slow part. Submit it even if you're unsure which Claude model you'll use; it
   covers all Anthropic models.
4. Done when each model shows **Access granted**. The surest test is one message in
   Bedrock → *Playground → Chat* with that model selected.

*Caveat:* AWS has been changing this flow. If your console has no *Model access*
page, models are enabled on first use instead, but the Anthropic use-case form
still appears the first time you use one in the Playground. Do that now for the
same reason.

## 3. Lambda and SageMaker quotas: check now, increases take hours to days

New accounts often start with Lambda concurrency at **10** (the AWS default is 1,000)
and **zero** SageMaker endpoint instances.

Console path (works before the CLI is installed): **Service Quotas** (region
us-east-1) → *AWS services* → search the service → search the quota.

- **Lambda → "Concurrent executions"**: request **1000**. The form rejects anything
  below the AWS default of 1,000, so that is the minimum you can ask for. 10 is
  enough to develop against, so don't wait on the approval.
- **SageMaker → "`<instance type>` for endpoint usage"**: request **1** for the
  instance type you'll deploy on, e.g. `ml.m5.xlarge` (CPU) or `ml.g4dn.xlarge`
  (GPU). These are examples; use whatever the inference plan settles on.

The same thing from the CLI, once step 5 is done:

```
aws service-quotas list-service-quotas --service-code lambda --region us-east-1 --query "Quotas[?QuotaName=='Concurrent executions'].[QuotaCode,Value]" --output table
aws service-quotas list-service-quotas --service-code sagemaker --region us-east-1 --query "Quotas[?contains(QuotaName,'for endpoint usage')].[QuotaName,QuotaCode,Value]" --output table
aws service-quotas request-service-quota-increase --service-code lambda --quota-code <QuotaCode from above> --desired-value 1000 --region us-east-1
```

## 4. BraTS cases: start the download now, it's large

Get **BraTS 2021 Task 1** (adult glioma). The converter expects its naming
(`_t1`, `_t1ce`, `_t2`, `_flair`, `_seg`) and 240×240×155 volumes.

- Official source: the RSNA-ASNR-MICCAI BraTS 2021 challenge on Synapse. It needs a
  Synapse account and joining the challenge, which can involve a wait.
- Faster: Kaggle mirrors exist (search "BraTS 2021 Task 1").
- The full training set is 1,251 cases and roughly 10+ GB. **You only need 3–5
  cases**, so if the source lets you pick individual cases, do that.
- **Write down the dataset version and licence terms shown on the download page.**
  Task 4 records them in `data/brain/SOURCE.md`.

Put each case in its own folder:

```
data\brain\raw\BraTS2021_00000\BraTS2021_00000_t1.nii.gz
                              \BraTS2021_00000_t1ce.nii.gz
                              \BraTS2021_00000_t2.nii.gz
                              \BraTS2021_00000_flair.nii.gz
                              \BraTS2021_00000_seg.nii.gz
```

`data/brain/raw/` is gitignored, so none of this goes to the public repo.
If you can only get BraTS 2023+ (it names the sequences `t1n / t1c / t2w / t2f`),
tell me before Task 4 and I'll map the names.

## 5. AWS CLI, an IAM user, and `aws configure`: 15 min

Do this yourself, and **don't paste the keys into chat**.

```
winget install Amazon.AWSCLI
```

Open a **new** terminal, then check with `aws --version`.

IAM user for programmatic access:

1. Console → IAM → *Users* → *Create user* → name `auralane-poc`.
2. *Attach policies directly* → **AdministratorAccess**. That is broad; it's
   acceptable only because this is a throwaway PoC account.
3. Open the user → *Security credentials* → *Create access key* → *Command Line
   Interface (CLI)*. Copy both values; the secret is shown once.

```
aws configure
    AWS Access Key ID:     <paste>
    AWS Secret Access Key: <paste>
    Default region name:   us-east-1
    Default output format: json
```

Must be **us-east-1**: HealthImaging isn't available in Mumbai. Check with:

```
aws sts get-caller-identity
aws configure get region
```

After the competition, delete the key:
`aws iam delete-access-key --user-name auralane-poc --access-key-id <id>`

## 6. Docker Desktop: 15–30 min

WSL2 with Ubuntu is already installed on this machine, so no `wsl --install` or
reboot for that.

```
winget install Docker.DockerDesktop
```

1. Log out and back in if the installer asks.
2. Start Docker Desktop, accept the terms.
3. Settings → General → **Use the WSL 2 based engine** should be ticked (it's the
   default).
4. Wait for **Engine running** (bottom left).

Check:

```
docker info --format "{{.ServerVersion}}"
docker run --rm hello-world
```

`orthanc` and `dynamodb` go green later, when Task 5 brings up
`docker-compose.local.yml`.

## 7. Tesseract OCR and PATH: 5 min

```
winget install UB-Mannheim.TesseractOCR
```

It installs to `C:\Program Files\Tesseract-OCR` and does **not** add itself to
PATH. Add it to your user PATH in PowerShell:

```
$p = [Environment]::GetEnvironmentVariable('Path','User')
[Environment]::SetEnvironmentVariable('Path', "$p;C:\Program Files\Tesseract-OCR", 'User')
```

Don't use `setx PATH ...`: it truncates PATH at 1,024 characters and copies the
system PATH into your user PATH.

Open a **new** terminal and run `tesseract --version`. If doctor says "installed
but not on PATH", the terminal is older than the PATH change.

This is what makes `sim/edge/test_deid.py` fully pass. Without it, the burned-in-text
test fails, and a de-identifier that can't see burned-in names is the failure that
test exists to catch.

## NIH PNGs: already done

5,606 PNGs are in `images/`. On a fresh machine: Kaggle `nih-chest-xrays/sample`
(~2 GB), copy the PNGs into `images/`. It's gitignored.
