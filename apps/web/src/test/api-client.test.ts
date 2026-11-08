import { api, AuthSession } from "../lib/api-client";

// Basic type verification test
const testSession: AuthSession = {
  access_token: "test_token",
  token_type: "bearer",
  user_id: "u-1",
  tenant_id: "t-1",
  role: "admin",
  email: "admin@invoiceflow.vn",
};

api.setSession(testSession);
if (api.getSession()?.email !== "admin@invoiceflow.vn") {
  throw new Error("Session management test failed");
}
api.setSession(null);
