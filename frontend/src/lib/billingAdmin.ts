export const ATHENS_TIME_ZONE = 'Europe/Athens';
export const AADE_GREEK_B2C_DOCUMENT_TYPE = '11.2';
export const AADE_GREEK_B2C_SERIES = '0';

export function currentEpochSeconds(): number {
    return Math.floor(Date.now() / 1000);
}

export function currentMinuteEpochSeconds(): number {
    return Math.floor(Date.now() / 60_000) * 60;
}

export function isSupportedAadeSeries(value: string): boolean {
    const normalized = value.trim();
    if (!normalized) {
        return false;
    }
    return Array.from(normalized).every((character) => (
        /[\p{L}\p{N}]/u.test(character)
        || '-._/'.includes(character)
    ));
}

export function isCanonicalAadeMark(value: string): boolean {
    if (!/^[1-9][0-9]{0,18}$/.test(value)) {
        return false;
    }
    return BigInt(value) <= BigInt('9223372036854775807');
}

type DateTimeParts = {
    year: number;
    month: number;
    day: number;
    hour: number;
    minute: number;
};

function parseDateTimeParts(value: string): DateTimeParts | null {
    const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
    if (!match) {
        return null;
    }
    const [, rawYear, rawMonth, rawDay, rawHour, rawMinute] = match;
    const parts = {
        year: Number(rawYear),
        month: Number(rawMonth),
        day: Number(rawDay),
        hour: Number(rawHour),
        minute: Number(rawMinute),
    };
    const validationDate = new Date(Date.UTC(
        parts.year,
        parts.month - 1,
        parts.day,
        parts.hour,
        parts.minute,
    ));
    if (
        validationDate.getUTCFullYear() !== parts.year
        || validationDate.getUTCMonth() !== parts.month - 1
        || validationDate.getUTCDate() !== parts.day
        || validationDate.getUTCHours() !== parts.hour
        || validationDate.getUTCMinutes() !== parts.minute
    ) {
        return null;
    }
    return parts;
}

function athensParts(epochMilliseconds: number): DateTimeParts {
    const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: ATHENS_TIME_ZONE,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
    }).formatToParts(new Date(epochMilliseconds));
    const values = Object.fromEntries(
        parts
            .filter((part) => part.type !== 'literal')
            .map((part) => [part.type, Number(part.value)]),
    );
    return {
        year: values.year,
        month: values.month,
        day: values.day,
        hour: values.hour,
        minute: values.minute,
    };
}

function sameDateTime(left: DateTimeParts, right: DateTimeParts): boolean {
    return left.year === right.year
        && left.month === right.month
        && left.day === right.day
        && left.hour === right.hour
        && left.minute === right.minute;
}

/**
 * Parse a datetime-local value as Europe/Athens, independently of the
 * administrator's browser time zone. Ambiguous or nonexistent DST minutes
 * fail closed instead of silently choosing the wrong instant.
 */
export function parseAthensDateTime(value: string): number | null {
    const requested = parseDateTimeParts(value);
    if (!requested) {
        return null;
    }
    const naiveUtc = Date.UTC(
        requested.year,
        requested.month - 1,
        requested.day,
        requested.hour,
        requested.minute,
    );
    const matches = new Set<number>();
    for (let offsetHours = 1; offsetHours <= 4; offsetHours += 1) {
        const candidate = naiveUtc - offsetHours * 60 * 60 * 1000;
        if (sameDateTime(athensParts(candidate), requested)) {
            matches.add(candidate);
        }
    }
    if (matches.size !== 1) {
        return null;
    }
    return Math.floor(Array.from(matches)[0] / 1000);
}

export function toAthensDateTimeValue(epochSeconds: number): string {
    const parts = athensParts(epochSeconds * 1000);
    const pad = (value: number) => String(value).padStart(2, '0');
    return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour)}:${pad(parts.minute)}`;
}
