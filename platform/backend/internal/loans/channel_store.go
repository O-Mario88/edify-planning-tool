package loans

import (
	"context"
	"errors"
	"fmt"
	"net/mail"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Channel is a Loan Partner of the Partner Directory and how it receives
// referrals.
type Channel struct {
	PartnerID, LenderName                               string
	HasLenderRecord, LenderActive, DataSharingAgreement bool
	ReferralsEnabled                                    bool
	DeliveryEmail, ConfirmedEmail, Description          string
	ConfirmedAt                                         *time.Time
	AwaitingConfirmation                                bool
	PortalUsers                                         int
}

// Eligible says whether the public form offers the lender now.
func (c Channel) Eligible() bool { return len(c.Problems()) == 0 }

// Problems say, in words, why the public form does not offer the lender.
func (c Channel) Problems() []string {
	var problems []string
	if !c.HasLenderRecord {
		problems = append(problems, "It has no lender record in the loan workflow. Save it as a Loan Partner again in the Partner Directory.")
	} else if !c.LenderActive {
		problems = append(problems, "Its lender record is inactive.")
	}
	if c.HasLenderRecord && !c.DataSharingAgreement {
		problems = append(problems, "No active data-sharing agreement is recorded for it.")
	}
	if !c.ReferralsEnabled {
		problems = append(problems, "Referrals are switched off.")
	}
	switch {
	case c.DeliveryEmail == "":
		problems = append(problems, "It has no receiving address.")
	case c.ConfirmedAt == nil || c.ConfirmedEmail != c.DeliveryEmail:
		problems = append(problems, "The lender has not yet confirmed its receiving address.")
	}
	return problems
}

// Channels are every active Loan Partner of the Partner Directory, by name.
func (s *Store) Channels(ctx context.Context, now time.Time) ([]Channel, error) {
	rows, err := s.db.Query(ctx, `
SELECT p.id, p.name, m.id IS NOT NULL, COALESCE(m.active AND m.deleted_at IS NULL, false),
  COALESCE(m.data_sharing_agreement_active, false), COALESCE(c.referrals_enabled, false),
  COALESCE(c.delivery_email, ''), COALESCE(c.confirmed_email, ''), COALESCE(c.description, ''), c.confirmed_at,
  COALESCE(c.confirm_expires_at > $1, false),
  (SELECT count(*) FROM bt_mfi_membership mm WHERE mm.mfi_id = m.id AND mm.active)
FROM partner p
LEFT JOIN bt_mfi_organization m ON m.id = p.loan_lender_id
LEFT JOIN school_loans.lender_channel c ON c.partner_id = p.id
WHERE p.partner_role = 'loan' AND p.active_status AND p.deleted_at IS NULL
ORDER BY p.name`, now)
	if err != nil {
		return nil, fmt.Errorf("loans: reading lender channels: %w", err)
	}
	defer rows.Close()
	var out []Channel
	for rows.Next() {
		var c Channel
		if err := rows.Scan(&c.PartnerID, &c.LenderName, &c.HasLenderRecord, &c.LenderActive, &c.DataSharingAgreement,
			&c.ReferralsEnabled, &c.DeliveryEmail, &c.ConfirmedEmail, &c.Description, &c.ConfirmedAt,
			&c.AwaitingConfirmation, &c.PortalUsers); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// ChannelUpdate is the Country Director's change to a lender's channel.
type ChannelUpdate struct {
	PartnerID, DeliveryEmail, Description string
	ReferralsEnabled                      bool
	ActorID, ActorName                    string
}

// SaveChannel stores the change. A new address is unconfirmed until the
// lender confirms it; the returned token, when not empty, is for the
// confirmation email.
func (s *Store) SaveChannel(ctx context.Context, update ChannelUpdate, now time.Time) (confirmToken string, err error) {
	email := strings.ToLower(strings.TrimSpace(update.DeliveryEmail))
	if email != "" {
		if parsed, err := mail.ParseAddress(email); err != nil || parsed.Address != email {
			return "", need("delivery_email", "Enter the lender's receiving address, such as loans@lender.org.")
		}
	}
	description := strings.TrimSpace(update.Description)
	if len([]rune(description)) > 280 {
		return "", need("description", "Keep the description to 280 characters.")
	}
	if update.ReferralsEnabled && email == "" {
		return "", need("delivery_email", "A lender needs a receiving address before referrals are switched on.")
	}
	err = s.inWrite(ctx, func(tx pgx.Tx) error {
		var isLoanPartner bool
		if err := tx.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM partner WHERE id = $1 AND partner_role = 'loan' AND deleted_at IS NULL)`,
			update.PartnerID).Scan(&isLoanPartner); err != nil {
			return err
		}
		if !isLoanPartner {
			return ErrNotFound
		}
		var previousEmail string
		var previousEnabled bool
		err := tx.QueryRow(ctx, `SELECT delivery_email, referrals_enabled FROM school_loans.lender_channel WHERE partner_id = $1 FOR UPDATE`,
			update.PartnerID).Scan(&previousEmail, &previousEnabled)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		changedAddress := email != "" && email != previousEmail
		var tokenHash *string
		var expires *time.Time
		if changedAddress {
			if confirmToken, err = NewToken(); err != nil {
				return err
			}
			hash, until := HashToken(confirmToken), now.Add(confirmLifetime)
			tokenHash, expires = &hash, &until
		}
		if _, err := tx.Exec(ctx, `
INSERT INTO school_loans.lender_channel (partner_id, referrals_enabled, delivery_email, description,
  confirm_token_hash, confirm_expires_at, updated_by, updated_by_name, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9)
ON CONFLICT (partner_id) DO UPDATE SET
  referrals_enabled = EXCLUDED.referrals_enabled,
  delivery_email = EXCLUDED.delivery_email,
  description = EXCLUDED.description,
  confirm_token_hash = CASE WHEN $10 THEN EXCLUDED.confirm_token_hash ELSE school_loans.lender_channel.confirm_token_hash END,
  confirm_expires_at = CASE WHEN $10 THEN EXCLUDED.confirm_expires_at ELSE school_loans.lender_channel.confirm_expires_at END,
  updated_by = EXCLUDED.updated_by, updated_by_name = EXCLUDED.updated_by_name, updated_at = EXCLUDED.updated_at`,
			update.PartnerID, update.ReferralsEnabled, email, description, tokenHash, expires,
			update.ActorID, update.ActorName, now, changedAddress); err != nil {
			return fmt.Errorf("loans: saving a lender channel: %w", err)
		}
		var notes []string
		if changedAddress {
			notes = append(notes, "Receiving address set to "+maskEmail(email)+"; awaiting the lender's confirmation.")
		}
		if update.ReferralsEnabled != previousEnabled {
			notes = append(notes, map[bool]string{true: "Referrals switched on.", false: "Referrals switched off."}[update.ReferralsEnabled])
		}
		if len(notes) == 0 {
			notes = append(notes, "Description updated.")
		}
		return channelEvent(ctx, tx, update.PartnerID, "channel_updated", update.ActorID, update.ActorName, strings.Join(notes, " "))
	})
	return confirmToken, err
}

// RenewConfirmation issues a new confirmation token for a lender's
// unconfirmed address.
func (s *Store) RenewConfirmation(ctx context.Context, partnerID, actorID, actorName string, now time.Time) (string, string, error) {
	token, err := NewToken()
	if err != nil {
		return "", "", err
	}
	var email string
	err = s.inWrite(ctx, func(tx pgx.Tx) error {
		err := tx.QueryRow(ctx, `
UPDATE school_loans.lender_channel SET confirm_token_hash = $2, confirm_expires_at = $3, updated_at = $4
WHERE partner_id = $1 AND delivery_email <> '' AND (confirmed_at IS NULL OR confirmed_email <> delivery_email)
RETURNING delivery_email`, partnerID, HashToken(token), now.Add(confirmLifetime), now).Scan(&email)
		if errors.Is(err, pgx.ErrNoRows) {
			return &FieldError{Field: "delivery_email", Message: "There is no unconfirmed address to confirm."}
		}
		if err != nil {
			return err
		}
		return channelEvent(ctx, tx, partnerID, "confirmation_sent", actorID, actorName,
			"Confirmation link sent to "+maskEmail(email)+".")
	})
	return token, email, err
}
