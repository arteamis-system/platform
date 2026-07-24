# Deploy-time policy. Evaluated by the dispatcher before a production deploy.
# Input is the resolved manifest plus the build outputs.
package platform.deploy

# Deny production deploys of unsigned images.
deny contains msg if {
	input.environment == "production"
	not input.image_signed
	msg := "production deploy requires a cosign-signed image"
}

# Deny production deploys that skipped the security gate.
deny contains msg if {
	input.environment == "production"
	input.security_gate != "success"
	msg := sprintf("security gate must pass before production (got %v)", [input.security_gate])
}

# Deny deploys below the project coverage floor.
deny contains msg if {
	input.coverage_min > 0
	input.coverage < input.coverage_min
	msg := sprintf("coverage %v%% is below the required %v%%", [input.coverage, input.coverage_min])
}
