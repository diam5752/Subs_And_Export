import { expand } from 'brace-expansion';

describe('patched dependency compatibility', () => {
    it('supports both legacy and current brace-expansion exports', () => {
        const legacyExpand = jest.requireActual('brace-expansion') as typeof expand & {
            expand: typeof expand;
        };

        expect(legacyExpand('{g,}subs')).toEqual(['gsubs', 'subs']);
        expect(expand('{s,v}tt')).toEqual(['stt', 'vtt']);
        expect(legacyExpand.expand).toBe(legacyExpand);
    });
});
