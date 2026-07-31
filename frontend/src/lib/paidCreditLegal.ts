import publicationIdentity from './paidCreditLegalPublication.json';

/**
 * Code-owned identity shared byte-for-byte with the backend image.
 *
 * It is intentionally not environment-controlled. Every wording or seller
 * identity change must ship a new non-draft version bound to the exact backend
 * EL/EN approval manifest before either surface remains operative.
 */
export function paidCreditLegalPublicationIsApproved(): boolean {
    return (
        publicationIdentity.schema_version === 1
        && publicationIdentity.status === 'approved'
        && publicationIdentity.public_terms_route === '/terms'
        && !publicationIdentity.terms_version.toLocaleLowerCase('en-US').includes('draft')
        && typeof publicationIdentity.approval_identity_sha256 === 'string'
        && /^[0-9a-f]{64}$/.test(publicationIdentity.approval_identity_sha256)
    );
}
