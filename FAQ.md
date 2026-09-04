# Frequently Asked Questions

### How do I access gcloud with authentication?
By default, the `gdc-admin` user is the only user configured with automatic access to `gcloud` authentication. 

If you want or need to access `gcloud` as a different user on the system, you can globally configure `gcloud` to use the shared access token by running the following command:

```bash
sudo gcloud config set --installation auth/access_token_file /run/gdc-auth/access_token
```
