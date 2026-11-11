// Package accountmail holds the account emails, word for word as the
// existing application sends them (apps/core/email.py MailerService), so a
// person gets the same message whichever system acted on their account.
package accountmail

import (
	"fmt"
	"strings"
)

// Message is one email.
type Message struct {
	Subject, Text string
}

const signature = "— Edify Planning and Monitoring Tool"

func lines(parts ...string) string { return strings.Join(parts, "\n") }

// PasswordReset is send_password_reset.
func PasswordReset(name, link string, minutes int) Message {
	return Message{
		Subject: "Reset your Edify Planning password",
		Text: lines("Hello "+name+",", "",
			"We received a request to reset your password. You can set a new one here:",
			link, "",
			fmt.Sprintf("This link expires in %d minutes and can only be used once.", minutes), "",
			"If you did not request a password reset, you can safely ignore this email.", "",
			signature),
	}
}

// Invitation is send_invitation.
func Invitation(name, invitedBy, link string) Message {
	return Message{
		Subject: "You have been invited to Edify Planning and Monitoring Tool",
		Text: lines("Hello "+name+",", "",
			invitedBy+" has invited you to join the Edify Planning and Monitoring Tool.", "",
			"To activate your account, set your password by opening this link:",
			link, "",
			"This invitation expires in 7 days and can only be used once.", "",
			"If you did not expect this invitation, you can safely ignore this email.", "",
			signature),
	}
}

// AccountCreated is send_temporary_password_notification.
func AccountCreated(name, createdBy, signInLink string) Message {
	return Message{
		Subject: "Your account has been created on Edify Planning and Monitoring Tool",
		Text: lines("Hello "+name+",", "",
			createdBy+" has created an account for you on the Edify Planning and Monitoring Tool.", "",
			"Your administrator has configured a temporary password for your account.",
			"You can log in using your email and that temporary password here:",
			signInLink, "",
			"Please update your password after logging in for the first time.", "",
			signature),
	}
}

// PasswordSetByAdmin is send_password_reset_by_admin_notification.
func PasswordSetByAdmin(name, resetBy, signInLink string) Message {
	return Message{
		Subject: "Your Edify account password has been reset",
		Text: lines("Hello "+name+",", "",
			"Your password has been reset by "+resetBy+".", "",
			"You can log in using your email and the new password provided by your administrator:",
			signInLink, "",
			"You will be required to change your password after logging in.", "",
			"If you did not expect this change, please contact your administrator immediately.", "",
			signature),
	}
}
