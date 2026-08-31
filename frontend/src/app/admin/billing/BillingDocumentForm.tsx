import { useEffect, useState } from "react";
import {
  type FieldErrors,
  type UseFormGetValues,
  type UseFormRegister,
  useForm,
} from "react-hook-form";
import { Spinner } from "@/components/Spinner";
import { useI18n } from "@/context/I18nContext";
import { ApiError, api, type RecordedAadeDocumentResponse } from "@/lib/api";
import {
  AADE_GREEK_B2C_DOCUMENT_TYPE,
  AADE_GREEK_B2C_SERIES,
  currentEpochSeconds,
  currentMinuteEpochSeconds,
  isCanonicalAadeMark,
  parseAthensDateTime,
  toAthensDateTimeValue,
} from "@/lib/billingAdmin";

type Translate = ReturnType<typeof useI18n>["t"];

type DocumentFormValues = {
  documentType: string;
  series: string;
  aa: string;
  mark: string;
  markRepeat: string;
  issuedAt: string;
  finalDocumentConfirmed: boolean;
};

type FieldProps = {
  register: UseFormRegister<DocumentFormValues>;
  errors: FieldErrors<DocumentFormValues>;
  t: Translate;
};

function FieldError({ message }: { message?: string }) {
  return message ? (
    <span role="alert" className="text-xs text-red-700">
      {message}
    </span>
  ) : null;
}

function DocumentTypeField({ register, errors, t }: FieldProps) {
  return (
    <label className="grid gap-2 text-sm font-semibold">
      {t("adminBillingDocumentType")}
      <input
        className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3"
        autoComplete="off"
        inputMode="decimal"
        readOnly
        aria-readonly="true"
        {...register("documentType", {
          required: t("adminBillingInvalidDocumentType"),
          validate: (value) =>
            value === AADE_GREEK_B2C_DOCUMENT_TYPE ||
            t("adminBillingInvalidDocumentType"),
        })}
      />
      <FieldError message={errors.documentType?.message} />
    </label>
  );
}

function SeriesField({ register, errors, t }: FieldProps) {
  return (
    <label className="grid gap-2 text-sm font-semibold">
      {t("adminBillingSeries")}
      <input
        className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3"
        autoComplete="off"
        readOnly
        aria-readonly="true"
        {...register("series", {
          required: t("adminBillingInvalidSeries"),
          validate: (value) =>
            value === AADE_GREEK_B2C_SERIES || t("adminBillingInvalidSeries"),
        })}
      />
      <FieldError message={errors.series?.message} />
    </label>
  );
}

function AaField({ register, errors, t }: FieldProps) {
  return (
    <label className="grid gap-2 text-sm font-semibold">
      {t("adminBillingAa")}
      <input
        className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3"
        autoComplete="off"
        inputMode="numeric"
        {...register("aa", {
          required: t("adminBillingInvalidAa"),
          maxLength: { value: 64, message: t("adminBillingInvalidAa") },
          pattern: { value: /^[0-9]+$/, message: t("adminBillingInvalidAa") },
        })}
      />
      <FieldError message={errors.aa?.message} />
    </label>
  );
}

function MarkField({ register, errors, t }: FieldProps) {
  return (
    <label className="grid gap-2 text-sm font-semibold">
      {t("adminBillingMark")}
      <input
        className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3 font-mono"
        autoComplete="off"
        inputMode="numeric"
        {...register("mark", {
          required: t("adminBillingInvalidMark"),
          validate: (value) =>
            isCanonicalAadeMark(value) || t("adminBillingInvalidMark"),
        })}
      />
      <FieldError message={errors.mark?.message} />
    </label>
  );
}

function MarkRepeatField({
  register,
  errors,
  getValues,
  t,
}: FieldProps & { getValues: UseFormGetValues<DocumentFormValues> }) {
  return (
    <label className="grid gap-2 text-sm font-semibold">
      {t("adminBillingMarkRepeat")}
      <input
        className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3 font-mono"
        autoComplete="off"
        inputMode="numeric"
        {...register("markRepeat", {
          required: t("adminBillingMarkMismatch"),
          validate: (value) =>
            value === getValues("mark") || t("adminBillingMarkMismatch"),
        })}
      />
      <FieldError message={errors.markRepeat?.message} />
    </label>
  );
}

function validateIssuedAt(
  value: string,
  paymentConfirmedAt: number,
  t: Translate,
): true | string {
  const issuedAt = parseAthensDateTime(value);
  if (issuedAt === null) return t("adminBillingInvalidIssuedAt");
  if (issuedAt > currentEpochSeconds()) return t("adminBillingFutureIssuedAt");
  if (issuedAt < paymentConfirmedAt) return t("adminBillingBeforePayment");
  return true;
}

function IssuedAtField({
  register,
  errors,
  paymentConfirmedAt,
  t,
}: FieldProps & { paymentConfirmedAt: number }) {
  return (
    <label className="grid gap-2 text-sm font-semibold">
      {t("adminBillingIssuedAt")}
      <input
        type="datetime-local"
        step="60"
        className="min-h-11 rounded-xl border border-[var(--border-strong)] bg-white px-3"
        {...register("issuedAt", {
          required: t("adminBillingInvalidIssuedAt"),
          validate: (value) => validateIssuedAt(value, paymentConfirmedAt, t),
        })}
      />
      <span className="text-xs font-normal leading-5 text-[var(--muted)]">
        {t("adminBillingAthensTimeHelp")}
      </span>
      <FieldError message={errors.issuedAt?.message} />
    </label>
  );
}

function DocumentFields({
  register,
  errors,
  getValues,
  paymentConfirmedAt,
  t,
}: FieldProps & {
  getValues: UseFormGetValues<DocumentFormValues>;
  paymentConfirmedAt: number;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <DocumentTypeField register={register} errors={errors} t={t} />
      <SeriesField register={register} errors={errors} t={t} />
      <AaField register={register} errors={errors} t={t} />
      <MarkField register={register} errors={errors} t={t} />
      <MarkRepeatField
        register={register}
        errors={errors}
        getValues={getValues}
        t={t}
      />
      <IssuedAtField
        register={register}
        errors={errors}
        paymentConfirmedAt={paymentConfirmedAt}
        t={t}
      />
    </div>
  );
}

function FormIntroduction({ t }: { t: Translate }) {
  return (
    <div>
      <h3 className="text-lg font-extrabold">
        {t("adminBillingDocumentTitle")}
      </h3>
      <p className="mt-2 max-w-4xl text-sm leading-6 text-[var(--muted)]">
        {t("adminBillingImmutableWarning")}
      </p>
      <p className="mt-2 max-w-4xl text-sm font-semibold leading-6 text-[var(--foreground)]">
        {t("adminBillingMizaiBaseline")}
      </p>
    </div>
  );
}

function FormActions({
  register,
  errors,
  recordError,
  isSubmitting,
  t,
}: FieldProps & { recordError: string; isSubmitting: boolean }) {
  return (
    <>
      <label className="flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-white p-4 text-sm font-semibold leading-6">
        <input
          type="checkbox"
          className="mt-1 h-5 w-5 shrink-0 accent-[var(--accent)]"
          {...register("finalDocumentConfirmed", {
            required: t("adminBillingFinalDocumentConfirm"),
          })}
        />
        <span>{t("adminBillingFinalDocumentConfirm")}</span>
      </label>
      <FieldError message={errors.finalDocumentConfirmed?.message} />
      {recordError && (
        <p
          role="alert"
          className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-900"
        >
          {recordError}
        </p>
      )}
      <button
        type="submit"
        disabled={isSubmitting}
        className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-[var(--foreground)] px-5 font-bold text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isSubmitting && <Spinner className="h-4 w-4" />}
        {isSubmitting ? t("adminBillingRecording") : t("adminBillingRecord")}
      </button>
    </>
  );
}

export function BillingDocumentForm({
  invoiceId,
  paymentConfirmedAt,
  onRecorded,
}: {
  invoiceId: string;
  paymentConfirmedAt: number;
  onRecorded: (record: RecordedAadeDocumentResponse) => void;
}) {
  const { t } = useI18n();
  const [recordError, setRecordError] = useState("");
  const {
    formState: { errors, isSubmitting },
    getValues,
    handleSubmit,
    register,
    setValue,
  } = useForm<DocumentFormValues>({
    defaultValues: {
      documentType: AADE_GREEK_B2C_DOCUMENT_TYPE,
      series: AADE_GREEK_B2C_SERIES,
      aa: "",
      mark: "",
      markRepeat: "",
      issuedAt: "",
      finalDocumentConfirmed: false,
    },
  });

  useEffect(() => {
    setValue("issuedAt", toAthensDateTimeValue(currentMinuteEpochSeconds()));
  }, [setValue]);

  const submitDocument = handleSubmit(async (values) => {
    const issuedAt = parseAthensDateTime(values.issuedAt);
    if (issuedAt === null) return;
    setRecordError("");
    try {
      const record = await api.recordIssuedAadeDocument(invoiceId, {
        document_type: values.documentType.trim(),
        series: values.series.trim(),
        aa: values.aa,
        mark: values.mark,
        issued_at: issuedAt,
      });
      onRecorded(record);
    } catch (error) {
      setRecordError(
        error instanceof ApiError && error.status === 403
          ? t("adminBillingRecentSignInRequired")
          : t("adminBillingRecordError"),
      );
    }
  });

  return (
    <form
      className="space-y-5"
      onSubmit={(event) => void submitDocument(event)}
      noValidate
    >
      <FormIntroduction t={t} />
      <DocumentFields
        register={register}
        errors={errors}
        getValues={getValues}
        paymentConfirmedAt={paymentConfirmedAt}
        t={t}
      />
      <FormActions
        register={register}
        errors={errors}
        recordError={recordError}
        isSubmitting={isSubmitting}
        t={t}
      />
    </form>
  );
}
